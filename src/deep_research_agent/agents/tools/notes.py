"""Note-graph tools - create / update / load notes.

Notes are the agents' persistent memory. Source notes hold the URL,
extracted claims, tier classification, and any summary the agent
wants to carry forward; question notes hold the question statement;
synthesis notes hold the agent's answer.

For the prototype we expose a minimal surface: source note create +
update, generic note load, and listing. More specialized tools can
layer on top once we see what the agents actually reach for.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from ...schemas.enums import ClaimType, NoteType, SourceState, Tier, VerificationStatus
from ...schemas.ids import NoteID
from ...schemas.note import (
    LandscapeMetadata,
    Link,
    Note,
    QuestionMetadata,
    SourceNoteMetadata,
)
from ...schemas.source import ClaimItem
from ..deps import Deps
from ..events import current_agent_id, instrumented
from ..memory import new_note_id
from ..schemas import QuestionSynthesis

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


# --- Tool input payloads ----------------------------------------------------
#
# pydantic-ai passes tool arguments through the LLM - the more explicit
# and small the payload shape, the less the model flails. Dedicated
# input models (with field docstrings) let us document tool semantics
# in one place.


class ClaimInput(BaseModel):
    """A claim extracted from a source, with the supporting quote."""

    text: str = Field(..., description="Paraphrased statement of the claim.")
    quote: str = Field(
        ...,
        min_length=1,
        description="Verbatim excerpt from the source that supports the claim.",
    )
    page_or_section: str | None = Field(
        None,
        description="Section heading or page reference, if known.",
    )


# --- Tools ------------------------------------------------------------------


@instrumented
async def create_source_note(
    ctx: RunContext[Deps],
    url: str,
    title: str,
    snippet: str = "",
    topics: list[str] | None = None,
) -> NoteID:
    """Record a source you've found but not yet read fully.

    If a source with the same URL already exists in memory, returns
    the existing NoteID (URL dedup). Otherwise creates a new SCOUTED
    source note. Does not fetch content - call fetch_url separately
    when you want to actually read it.

    Args:
      url: Full URL of the source. Dedup is URL-keyed with trivial
        normalization (lowercased scheme/host, trailing slash
        stripped), so calling this twice on the same link is safe.
      title: Human-readable title. Pass whatever the search result
        gave you; defaults to the URL if empty.
      snippet: Short excerpt or abstract from the search result (a
        sentence or two). Becomes the source note's summary until
        an analyst reads the full content.
      topics: Optional 1-3 short topic labels (e.g. ['benchmarks',
        'evaluation-methodology']). Used by the landscape agent to
        cluster sources and by the researcher to see corpus shape
        at a glance. Can be empty.
    """
    existing = ctx.deps.memory.find_source_by_url(url)
    if existing is not None:
        # Merge topics if the caller supplied new ones - helps when
        # landscape scouts the same URL on two different rounds with
        # different topic framings.
        if topics:
            existing_meta = existing.metadata
            assert isinstance(existing_meta, SourceNoteMetadata)
            merged = list(dict.fromkeys([*existing_meta.topics, *topics]))
            if merged != existing_meta.topics:
                new_meta = existing_meta.model_copy(update={"topics": merged})
                await ctx.deps.memory.update(existing.id, metadata=new_meta)
        return existing.id

    source_id = new_note_id("source")
    note = Note(
        id=source_id,
        type=NoteType.SOURCE,
        title=title or url,
        description=snippet[:280],
        content="",
        metadata=SourceNoteMetadata(
            url=url,
            title=title or "Untitled",
            state=SourceState.SCOUTED,
            summary=snippet or None,
            topics=list(topics or []),
        ),
        last_modified_at=_now(),
        created_at=_now(),
    )
    await ctx.deps.memory.create(note)
    return source_id


@instrumented
async def update_source_after_reading(
    ctx: RunContext[Deps],
    source_id: NoteID,
    tier: int,
    tier_rationale: str,
    peer_reviewed: bool,
    summary: str,
    relevance_note: str,
    claims: list[ClaimInput] | None = None,
) -> str:
    """Record what you learned after reading a source.

    Call this after fetch_url returns content for a source and you've
    read enough of it to classify its quality and extract key claims.
    Promotes the source from SCOUTED to ANALYZED.

    Args:
      source_id: NoteID of the source note you're updating. Must be an
        existing source_note id (from create_source_note or
        list_source_notes).
      tier: Integer 1..5 rating source quality. 1 = peer-reviewed
        research in strong venues. 2 = arXiv preprint or well-cited
        technical report. 3 = reputable industry post, official docs,
        respected newsletter. 4 = community writeup, unreviewed blog.
        5 = low-quality, promotional, or off-topic (you can still
        record these but they shouldn't carry much weight).
      tier_rationale: One sentence explaining why you assigned this
        tier (e.g. "peer-reviewed NeurIPS paper with 200+ citations").
      peer_reviewed: True iff this source went through formal peer
        review. arXiv preprints are NOT peer-reviewed; conference
        papers typically are.
      summary: 2-4 sentences summarizing the source's main argument
        or findings in your own words. Goes onto the source note's
        human-readable blurb.
      relevance_note: One sentence on why this source matters for the
        question you're investigating. Helps a future reader
        (including the top-level researcher) see at a glance why this
        source was kept.
      claims: List of 3-6 key claims extracted from the source. Each
        claim MUST include a verbatim quote from the source text.
        Never paraphrase a quote - if you can't find a supporting
        quote, drop the claim. Pass an empty list if the source
        turned out to be unhelpful.

    Returns a one-line confirmation string. If source_id isn't a
    source_note in memory, raises ModelRetry so you can call
    list_source_notes and try again with a valid id.
    """
    try:
        tier_enum = Tier(tier)
    except ValueError as exc:
        raise ModelRetry(
            f"tier must be an integer 1..5; got {tier!r}. "
            "Pick the number that best matches the source quality."
        ) from exc

    existing = ctx.deps.memory.get(source_id)
    if existing is None:
        raise ModelRetry(
            f"source note {source_id!r} not in memory. "
            "Call list_source_notes() to see valid source ids, "
            "or create the source first with create_source_note()."
        )
    if existing.type != NoteType.SOURCE:
        raise ModelRetry(
            f"note {source_id!r} is a {existing.type.value}, not a source_note. "
            "Pass a source_note id here."
        )

    claim_items: list[ClaimItem] = []
    for i, c in enumerate(claims or []):
        claim_items.append(
            ClaimItem(
                id=f"{source_id}-c{i}",
                text=c.text,
                quote=c.quote,
                page_or_section=c.page_or_section,
                extractor_confidence=0.8,
                verification_status=VerificationStatus.UNVERIFIED,
                claim_type=ClaimType.EXTERNAL,
            )
        )

    existing_meta = existing.metadata
    assert isinstance(existing_meta, SourceNoteMetadata)
    new_meta = existing_meta.model_copy(
        update={
            "state": SourceState.ANALYZED,
            "tier": tier_enum,
            "tier_rationale": tier_rationale,
            "peer_reviewed": peer_reviewed,
            "summary": summary,
            "claims": claim_items,
        }
    )
    await ctx.deps.memory.update(
        source_id,
        description=summary[:280] or existing.description,
        content=relevance_note,
        metadata=new_meta,
    )
    return f"source {source_id} tier={tier} peer_reviewed={peer_reviewed} claims={len(claim_items)}"


@instrumented
async def load_note(ctx: RunContext[Deps], note_id: NoteID) -> dict[str, object]:
    """Load any note by ID - returns its full contents as a dict.

    Use this to re-read a source note (with its extracted claims +
    summary) when composing a synthesis, or to inspect a question
    note created by another agent. Returns {"error": ...} if the
    note isn't in memory - check the id and try again.

    Args:
      note_id: NoteID to load. Any note type (source / question /
        landscape / etc.) - the returned dict includes the note's
        type-specific metadata.
    """
    note = ctx.deps.memory.get(note_id)
    if note is None:
        return {"error": f"note {note_id} not found"}
    return note.model_dump(mode="json")


@instrumented
async def list_source_notes(
    ctx: RunContext[Deps], only_analyzed: bool = False
) -> list[dict[str, object]]:
    """List source notes in memory with their key metadata.

    Returns one dict per source with id / url / title / state /
    tier / peer_reviewed / summary / n_claims. Use this to audit
    what's been gathered so far, to pick sources to cite in a
    synthesis, or to inherit the landscape agent's scouted sources
    before running your own searches.

    Args:
      only_analyzed: If True, only return sources that have already
        been read (state == ANALYZED). Default False - returns all
        sources including SCOUTED ones that haven't been read yet.
    """
    sources = ctx.deps.memory.list_by_type(NoteType.SOURCE)
    out: list[dict[str, object]] = []
    for n in sources:
        meta = n.metadata
        if not isinstance(meta, SourceNoteMetadata):
            continue
        if only_analyzed and meta.state != SourceState.ANALYZED:
            continue
        out.append(
            {
                "id": n.id,
                "url": meta.url,
                "title": meta.title,
                "state": meta.state.value,
                "tier": meta.tier.value if meta.tier is not None else None,
                "peer_reviewed": meta.peer_reviewed,
                "summary": meta.summary,
                "n_claims": len(meta.claims or []),
            }
        )
    return out


@instrumented
async def get_research_state(ctx: RunContext[Deps]) -> dict[str, object]:
    """Compact snapshot of the note graph for the orchestrator.

    Returns:
      {
        "root_question": {...} | None,
        "questions": [{id, question, status, confidence, bottom_line,
                       parent_id, n_sources_cited}, ...],
        "sources_by_tier": {"unclassified": N, "1": N, "2": N, ...},
        "sources_by_state": {"SCOUTED": N, "FETCHED": N, "ANALYZED": N},
        "budget": {"analyst_dispatches_remaining": int | None},
      }

    This is the ONLY way the researcher should inspect the note graph
    between rounds - it keeps the researcher's context free of raw
    source content.
    """
    from ...schemas.note import QuestionMetadata, SourceNoteMetadata

    root_id = ctx.deps.outputs.get("__root_question_id__")
    questions = []
    root_summary: dict[str, object] | None = None
    for n in ctx.deps.memory.list_by_type(NoteType.QUESTION):
        meta = n.metadata
        if not isinstance(meta, QuestionMetadata):
            continue
        entry = {
            "id": n.id,
            "question": n.description or n.title,
            "status": meta.status,
            "confidence": meta.confidence,
            "bottom_line": meta.bottom_line,
            "parent_id": meta.parent_question_id,
            "n_sources_cited": len(meta.sources_cited),
        }
        if n.id == root_id:
            root_summary = entry
        else:
            questions.append(entry)

    sources_by_tier: dict[str, int] = {}
    sources_by_state: dict[str, int] = {}
    for n in ctx.deps.memory.list_by_type(NoteType.SOURCE):
        meta = n.metadata
        if not isinstance(meta, SourceNoteMetadata):
            continue
        tier_key = str(meta.tier.value) if meta.tier is not None else "unclassified"
        sources_by_tier[tier_key] = sources_by_tier.get(tier_key, 0) + 1
        sources_by_state[meta.state.value] = sources_by_state.get(meta.state.value, 0) + 1

    budget_remaining = ctx.deps.outputs.get("__analyst_budget__")

    return {
        "root_question": root_summary,
        "questions": questions,
        "sources_by_tier": sources_by_tier,
        "sources_by_state": sources_by_state,
        "budget": {
            "analyst_dispatches_remaining": (
                budget_remaining if isinstance(budget_remaining, int) else None
            ),
        },
    }


@instrumented
async def create_question_note(
    ctx: RunContext[Deps],
    question: str,
    classification: str = "synthesis",
) -> NoteID:
    """Record a sub-question you plan to investigate.

    Typically called from the top-level researcher to register a
    sub-question before dispatching an analyst on it. Returns the
    new question NoteID.

    Args:
      question: The question text. A good sub-question is focused,
        independently answerable with a few sources, and doesn't
        overlap with sibling sub-questions.
      classification: One of 'lookup' / 'synthesis' / 'contested' /
        'sparse'. 'lookup' = a factual question with a clear answer;
        'synthesis' = integrative question across multiple sources;
        'contested' = question where sources are known to disagree;
        'sparse' = question with limited source coverage. Default is
        'synthesis'.
    """
    from ...schemas.enums import QuestionClassification

    try:
        cls = QuestionClassification(classification)
    except ValueError as exc:
        raise ModelRetry(
            "classification must be one of: lookup, synthesis, contested, sparse; "
            f"got {classification!r}"
        ) from exc

    q_id = new_note_id("question")
    note = Note(
        id=q_id,
        type=NoteType.QUESTION,
        title=question[:120],
        description=question,
        content="",
        metadata=QuestionMetadata(classification=cls),
        last_modified_at=_now(),
        created_at=_now(),
    )
    await ctx.deps.memory.create(note)
    return q_id


# --- Final-output tools ----------------------------------------------------
#
# These are how agents COMMIT their final work. Replaces structured-
# output validation on the agent. Moving this to a tool means:
#
# 1. Pydantic validates tool args -> invalid args surface as a
#    ModelRetry with a descriptive error that the model sees as a
#    tool-call failure and naturally retries within the same turn.
# 2. The tool can create a durable synthesis_note on success, so the
#    work survives a later crash in the conversation.
# 3. Tool-call events fire in the UI - the user sees the write
#    attempt land (or fail + retry) in the agent card.
#
# Each tool stashes its structured payload in `deps.outputs[agent_id]`
# so the wrapping `*_run` function can read the committed data
# without relying on the agent's stringy final message.


@instrumented
async def answer_question(
    ctx: RunContext[Deps],
    question_id: NoteID,
    bottom_line: str,
    synthesis: str,
    confidence: str,
    sources_cited: list[NoteID] | None = None,
    disagreements: list[str] | None = None,
    open_issues: list[str] | None = None,
) -> str:
    """Commit your answer to a pre-created question note.

    This is the TERMINAL tool for both the analyst (answering its
    assigned sub-question) and the researcher (answering the root
    question, which produces the final report). Updates the QUESTION
    note's metadata in place (status -> SYNTHESIZED) so a question's
    question + answer live on one note.

    You MUST supply all five required fields. A call with only
    question_id + confidence will be rejected - bottom_line and
    synthesis are the actual answer and carry the work.

    Args:
      question_id: NoteID of the QUESTION note you're answering. For
        analysts: the id passed in your opening message. For the
        researcher: the root question id from get_research_state's
        `root_question.id`. This note MUST already exist - the
        caller creates it before dispatch.
      bottom_line: REQUIRED. One or two plain-English sentences that
        directly answer the question. This is what a reader will see
        at a glance; don't hedge or wander. For the root question,
        this is the 2-4 sentence executive summary of the whole
        investigation.
      synthesis: REQUIRED. The full markdown write-up. For analysts,
        multiple paragraphs synthesizing evidence from the sources
        you read - cite source notes inline using [source-abc123]
        syntax. For the researcher, this is the entire final report
        synthesizing across sub-questions; cite source notes inline
        the same way and reference sub-question bottom lines. Do not
        leave this empty - it's the actual report content.
      confidence: REQUIRED. One of 'high' / 'medium' / 'low'
        (case-insensitive). Reflects source quality and convergence
        of the evidence.
      sources_cited: Optional list of source NoteIDs whose claims
        support this answer. Can be empty if truly nothing relevant
        was found, but every substantive claim in `synthesis` should
        trace to a cited source.
      disagreements: Optional list of short strings describing
        points where sources conflict. Empty if findings converge
        cleanly. Don't paper over genuine disagreement.
      open_issues: Optional list of short strings describing things
        this answer couldn't cover (paywalls, missing sources,
        tiebreakers needed). Empty if coverage was adequate.

    Returns a confirmation string. Raises ModelRetry if question_id
    isn't a valid question_note id - call get_research_state or
    pass the id from your opening message and try again.
    """
    confidence_lc = confidence.strip().lower()
    if confidence_lc not in {"high", "medium", "low"}:
        raise ModelRetry(f"confidence must be 'high', 'medium', or 'low'; got {confidence!r}")

    existing = ctx.deps.memory.get(question_id)
    if existing is None:
        raise ModelRetry(
            f"question note {question_id!r} not in memory. "
            "The researcher should have created the question note before "
            "dispatching you; if you're seeing this, pass the question_id "
            "exactly as it was given in your opening message."
        )
    if existing.type != NoteType.QUESTION:
        raise ModelRetry(
            f"note {question_id!r} is a {existing.type.value}, not a question_note. "
            "Pass the question id you were assigned."
        )

    existing_meta = existing.metadata
    assert isinstance(existing_meta, QuestionMetadata)
    agent_id = current_agent_id() or "anonymous"
    new_meta = existing_meta.model_copy(
        update={
            "status": "SYNTHESIZED",
            "bottom_line": bottom_line,
            "synthesis_markdown": synthesis,
            "confidence": confidence_lc,
            "sources_cited": list(sources_cited or []),
            "disagreements": list(disagreements or []),
            "open_issues": list(open_issues or []),
            "answered_by_agent_id": agent_id,
        }
    )
    await ctx.deps.memory.update(
        question_id,
        description=bottom_line[:280] or existing.description,
        content=synthesis,
        links=[Link(target_id=src, edge_type="cites") for src in (sources_cited or [])],
        metadata=new_meta,
    )

    # Stash so the wrapping *_run function can read the structured
    # payload without reconstructing from the note.

    qs = QuestionSynthesis(
        question=existing.description or existing.title,
        bottom_line=bottom_line,
        synthesis=synthesis,
        confidence=confidence_lc,
        sources_cited=list(sources_cited or []),
        disagreements=list(disagreements or []),
        open_issues=list(open_issues or []),
    )
    ctx.deps.outputs[agent_id] = qs
    return (
        f"answered question {question_id} "
        f"({confidence_lc} confidence, {len(qs.sources_cited)} sources cited)"
    )


@instrumented
async def write_landscape_brief(
    ctx: RunContext[Deps],
    brief_markdown: str,
) -> str:
    """Commit your landscape brief for the researcher to read.

    TERMINAL tool for the landscape agent - call exactly once as the
    last tool call before ending your turn. Creates a LANDSCAPE note
    that the downstream researcher reads to decide how to decompose
    the query.

    Args:
      brief_markdown: REQUIRED, non-empty. Free-form markdown summary
        of the terrain you scouted (~300-600 words). Include whatever
        is genuinely useful for a researcher deciding how to
        decompose the query, choosing freely among:
          - apparent sub-areas or themes the corpus splits into
          - obvious gaps / under-covered angles
          - terminology the field uses (so the researcher can ask
            sharper sub-questions)
          - source clusters (which venues, which kinds of outlets)
          - contested points you noticed in the snippets
        Do NOT paraphrase full source content - the researcher sees
        the source list separately and doesn't need a summary of
        each one. Cite sources inline with [source-abc123] when you
        call out specific examples.
    """

    if not brief_markdown.strip():
        raise ModelRetry(
            "brief_markdown must be non-empty - this field is the actual brief "
            "the researcher will read. Write a short markdown summary of the terrain."
        )

    agent_id = current_agent_id() or "anonymous"
    # Stash raw markdown for landscape_run to forward to the researcher.
    ctx.deps.outputs[agent_id] = brief_markdown

    # Durable landscape note.
    note_id = new_note_id("landscape")
    note = Note(
        id=note_id,
        type=NoteType.LANDSCAPE,
        title="Landscape brief",
        description=brief_markdown.splitlines()[0][:280] if brief_markdown else "",
        content=brief_markdown,
        metadata=LandscapeMetadata(raw_query=""),  # query filled by landscape_run
        last_modified_at=_now(),
        created_at=_now(),
    )
    await ctx.deps.memory.create(note)
    return f"committed landscape brief as {note_id}"
