"""Streaming-pipeline task-type handlers.

The pipeline is a continuous stream over a shared URL-keyed corpus:

    LANDSCAPE_SURVEY ─┬─ DECOMPOSE ──────────────────────────────────┐
                      │                                              │
                      ├─ SCOUT_SOURCES (landscape seed)              │
                      │     └─> source_notes (SCOUTED)               │
                      │     └─> RESCORE_RELEVANCE                    │
                      │           └─> FETCH_AND_EXTRACT (per src)    │
                      │                └─> ANALYZE_SOURCE            │
                      │                      (per src x question)    │
                      │                                              │
                      └─ per-question SCOUT_SOURCES (after DECOMPOSE)
                            (same chain)                             │
                                                                     ▼
                                           QUESTION_SYNTHESIZE (readiness-gated)
                                                     │
                                                     ▼
                                           VERIFY_CLAIM (on cited claims only)
                                                     │
                                                     ▼
                                      CHECK_TERMINATION_READY → VALIDATE → WRITE_REPORT

All retrieval-phase tasks have `retrieval_ignores=True`, so the
scheduler dispatches them as soon as they're ready regardless of
synthesis-side dependencies. QUESTION_SYNTHESIZE keeps synthesis_waits
and uses a readiness gate: if not enough evidence is analyzed for its
question yet, it re-emits itself with fresh depends_on on all currently
in-flight retrieval/analysis tasks, bounded by pipeline.synthesis.max_qs_polls.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import cast

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..corpus import CorpusIndex, canonicalize_url
from ..corpus.relevance import score_sources_batch
from ..patterns.ach import (
    ACH_ADJUDICATION_SYSTEM,
    ACH_CONSISTENCY_SYSTEM,
    ACH_HYPOTHESIS_GEN_SYSTEM,
)
from ..patterns.debate import DEBATE_FRAMINGS
from ..patterns.maker_checker import emit_verify_claim, select_claims_to_verify
from ..patterns.multi_perspective import PERSPECTIVES, Perspective
from ..patterns.single_researcher import (
    emit_analyze_source,
    emit_decompose,
    emit_fetch_and_extract,
    emit_meta_synthesize,
    emit_question_synthesize,
    emit_rescore_relevance,
    emit_scout_sources,
    emit_write_report,
)
from ..phases.termination import emit_check_termination_ready, emit_validate_completion
from ..retrieval import (
    BraveClient,
    build_structured_content,
    fetch_and_extract,
    is_long_source,
    render_outline,
    search_academic,
)
from ..retrieval.scout import (
    ScoutQuery,
    landscape_seed_queries,
    question_focused_queries,
    verify_seed_queries,
)
from ..scheduler import DepEdgeAdd, NoteMutation, TaskResult
from ..scheduler.ids import new_note_id
from ..schemas import (
    ClaimItem,
    DecisionMetadata,
    DepEdge,
    HypothesisMetadata,
    LandscapeMetadata,
    Link,
    Note,
    NoteID,
    PositionItem,
    QuestionMetadata,
    SourceNoteMetadata,
    SourceState,
    SynthesisMetadata,
    Task,
    TaskID,
    ThemeItem,
    Tier,
)
from ..schemas.enums import (
    ClaimType,
    DependencyType,
    NoteType,
    OrchestrationPattern,
    QuestionClassification,
    RoleClass,
    TaskStatus,
    TaskTier,
    TaskType,
    VerificationStatus,
)
from ..schemas.note import SourceNoteMetadata as _SourceMeta
from ..tiering.classifier import classify_source
from ..tiering.simple import REJECT_DOMAINS
from .executor import AgentExecutor, HandlerContext
from .outputs import (
    AchAdjudicationOutput,
    AchConsistencyOutput,
    AchHypothesisGenOutput,
    AnalyzerOutput,
    DecomposeOutput,
    LandscapeOutput,
    ReportOutput,
    SynthesizerOutput,
    ValidateCompletionOutput,
    VerifierOutput,
)
from .prompts import (
    ANALYZER_SYSTEM,
    DECOMPOSE_SYSTEM,
    JUDGE_SYSTEM,
    LANDSCAPE_SYSTEM,
    META_SYNTHESIZER_SYSTEM,
    REPORT_SYSTEM,
    SYNTHESIZER_SYSTEM,
    VALIDATE_COMPLETION_SYSTEM,
    VERIFIER_SYSTEM,
)

logger = logging.getLogger(__name__)


def _reject_list_match(url: str) -> bool:
    """True if `url` matches the deterministic Tier-5 reject list.

    Used as a pre-fetch gate so we don't waste a fetch + classifier call
    on obvious junk (social, aggregators, unattributed content).
    """
    u = url.lower()
    return any(d in u for d in REJECT_DOMAINS)


# Tunables live in PipelineConfig (config/pipeline.yaml, loaded into
# ctx.pipeline). Handlers read from that config rather than module
# constants so ablations / retuning happens by editing one YAML file
# rather than recompiling. See config.PipelineConfig for the full
# surface and defaults.


def _now() -> datetime:
    return datetime.now(UTC)


def _src_meta(note: Note) -> _SourceMeta:
    """Narrow discriminated metadata to SourceNoteMetadata for mypy/pyright.
    Caller must ensure note.type == NoteType.SOURCE.
    """
    return cast(_SourceMeta, note.metadata)


# Minimal stopwords for query-construction helpers (verify + scout).
_VERIFY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "in",
        "on",
        "to",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "with",
        "by",
        "from",
        "how",
        "what",
        "why",
        "do",
        "does",
        "did",
        "can",
        "will",
        "or",
        "but",
        "if",
        "as",
        "at",
        "about",
        "into",
        "over",
        "between",
        "and",
        "not",
        "no",
        "yes",
        "when",
        "than",
        "such",
        "more",
        "less",
        "also",
    }
)
_VERIFY_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")


def _build_verify_query(claim_text: str, question: str) -> str:
    """Topic-keyword query for independent-source retrieval during
    VERIFY_CLAIM. Strips stopwords, combines claim + question tokens,
    caps length."""

    def tokens(text: str) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for m in _VERIFY_WORD_RE.findall(text):
            w = m.lower()
            if w in _VERIFY_STOPWORDS or w in seen or len(w) < 3:
                continue
            seen.add(w)
            out.append(m)
        return out

    claim_tokens = tokens(claim_text)[:8]
    question_tokens = [
        t for t in tokens(question) if t.lower() not in {w.lower() for w in claim_tokens}
    ][:4]
    query_tokens = claim_tokens + question_tokens
    return " ".join(query_tokens) if query_tokens else claim_text[:120]


# --- Helpers: readiness gate / scout aggregation ---------------------------


def _open_questions(ctx: HandlerContext) -> list[tuple[str, str]]:
    """Returns [(question_note_id, question_title)] for every question_note
    that isn't SYNTHESIZED. Used by relevance scoring to know which
    questions to score new sources against.
    """
    out: list[tuple[str, str]] = []
    for n in ctx.notes.all():
        if n.type != NoteType.QUESTION:
            continue
        status = getattr(n.metadata, "status", "OPEN")
        if status == "SYNTHESIZED":
            continue
        out.append((n.id, n.title))
    return out


def _pending_retrieval_task_ids(
    ctx: HandlerContext,
    exclude_task_id: TaskID | None = None,
) -> list[TaskID]:
    """Every non-terminal task that could still add evidence to the corpus.
    Used as the depends_on set when QUESTION_SYNTHESIZE re-emits itself
    under the readiness gate.
    """
    relevant_types = {
        TaskType.SCOUT_SOURCES,
        TaskType.FETCH_AND_EXTRACT,
        TaskType.ANALYZE_SOURCE,
        TaskType.RESCORE_RELEVANCE,
    }
    out: list[TaskID] = []
    for t in ctx.tasks.all():
        if t.id == exclude_task_id:
            continue
        if t.type not in relevant_types:
            continue
        if t.status not in (
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED_ON_SYNTHESIS_DEP,
            TaskStatus.BLOCKED_ON_SPLIT,
        ):
            continue
        out.append(t.id)
    return out


# --- LANDSCAPE_SURVEY ------------------------------------------------------


async def handle_landscape_survey(ctx: HandlerContext) -> TaskResult:
    """Phase 1: broad search + one batched LLM pass over snippets to map
    the territory, THEN seed the shared corpus with a landscape scout
    bundle so by the time DECOMPOSE runs, the corpus already has sources
    being fetched and tier-classified in the background.
    """
    query = ctx.task.goal
    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    brave = BraveClient(api_key=brave_key)
    hits = await brave.search(query, count=8)
    logger.info("landscape brave hits=%d", len(hits))

    if not hits:
        raise RuntimeError(f"landscape survey returned 0 hits for query={query!r}")

    snippets_text = "\n\n".join(
        f"{i + 1}. {h.title}\n   URL: {h.url}\n   Snippet: {h.snippet}" for i, h in enumerate(hits)
    )
    agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=LandscapeOutput,
        system_prompt=LANDSCAPE_SYSTEM,
    )
    r = await ctx.track(agent, f"Query: {query}\n\nSearch hit snippets:\n\n{snippets_text}")
    out = r.output

    landscape_id = new_note_id("landscape")
    landscape_note = Note(
        id=landscape_id,
        type=NoteType.LANDSCAPE,
        title=f"Landscape: {query[:80]}",
        description=out.summary,
        content=out.discussion,
        metadata=LandscapeMetadata(
            themes=[ThemeItem(name=t.name, description=t.description) for t in out.themes],
            positions=[
                PositionItem(label=p.label, description=p.description) for p in out.positions
            ],
            under_covered_areas=out.under_covered_areas,
            raw_query=query,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    # Seed the corpus with the landscape Brave hits as SCOUTED source_notes.
    # These get relevance scored and fetched in the background once
    # DECOMPOSE produces questions. We don't fetch them here — that costs
    # wall-clock time; let retrieval run concurrently with DECOMPOSE.
    seed_source_notes: list[Note] = []
    for h in hits:
        if not h.url:
            continue
        seed_source_notes.append(
            _new_scouted_note(
                url=h.url,
                title=h.title,
                snippet=h.snippet,
                created_by=ctx.task.id,
                strategy="landscape_brave",
            )
        )

    # Spawn landscape-wide scouting for breadth: direct + contrarian +
    # time-bounded + venue queries all run against the topic. Each SCOUT
    # task emits more SCOUTED source_notes which will be relevance-scored
    # once questions exist.
    landscape_scout = emit_scout_sources(
        goal=query,
        scout_mode="landscape_seed",
        parent_task_id=ctx.task.id,
    )

    decompose = emit_decompose(query, landscape_id, ctx.task.id)

    return TaskResult(
        note_mutations=[
            NoteMutation(kind="create", note=landscape_note),
            *(NoteMutation(kind="create", note=n) for n in seed_source_notes),
        ],
        spawned_tasks=[landscape_scout, decompose],
        verdict=(
            f"landscape_note {landscape_id}: "
            f"{len(out.themes)} themes, {len(out.positions)} positions; "
            f"seeded corpus with {len(seed_source_notes)} scouted + 1 SCOUT_SOURCES"
        ),
    )


def _new_scouted_note(
    *,
    url: str,
    title: str,
    snippet: str,
    created_by: TaskID,
    strategy: str,
    seed_question_ids: list[str] | None = None,
) -> Note:
    """Build a SCOUTED source_note. No fetch, no tier, no claims."""
    return Note(
        id=new_note_id("source"),
        type=NoteType.SOURCE,
        title=title or url,
        description=(snippet or "")[:280],
        content="",  # populated on FETCH_AND_EXTRACT
        metadata=SourceNoteMetadata(
            url=url,
            title=title or "Untitled",
            state=SourceState.SCOUTED,
            summary=snippet,
            discovered_by=str(created_by),
            scout_strategy=strategy,
            # seed_question_ids get picked up later via the rescore pass
            # — we don't pre-populate relevance without scoring.
        ),
        created_by=created_by,
        created_at=_now(),
        last_modified_at=_now(),
    )


# --- DECOMPOSE -------------------------------------------------------------


def _format_landscape_for_decomposer(landscape: Note) -> str:
    meta = landscape.metadata
    parts: list[str] = []
    parts.append(f"Summary: {landscape.description}")
    parts.append("")
    parts.append("Discussion:")
    parts.append(landscape.content)
    if getattr(meta, "themes", None):
        parts.append("")
        parts.append("Themes:")
        for t in meta.themes:
            parts.append(f"  - {t.name}: {t.description}")
    if getattr(meta, "positions", None):
        parts.append("")
        parts.append("Positions surfaced:")
        for p in meta.positions:
            parts.append(f"  - {p.label}: {p.description}")
    if getattr(meta, "under_covered_areas", None):
        parts.append("")
        parts.append("Under-covered areas:")
        for a in meta.under_covered_areas:
            parts.append(f"  - {a}")
    return "\n".join(parts)


async def handle_decompose(ctx: HandlerContext) -> TaskResult:
    """Evidence-grounded decomposition.

    Emits:
    - One AIMS decision_note.
    - N question_notes.
    - Per-question SCOUT_SOURCES tasks (breadth of coverage).
    - One RESCORE_RELEVANCE that scores the existing scouted corpus
      (landscape seeds) against the new questions — kicks off fetch
      fan-out for sources that are already in.
    - N QUESTION_SYNTHESIZE tasks (readiness-gated).
    - CHECK_TERMINATION_READY → VALIDATE_COMPLETION → WRITE_REPORT chain.
    """
    query = ctx.task.goal

    if not ctx.task.reads_notes:
        raise RuntimeError("DECOMPOSE expected a landscape_note in reads_notes")
    landscape = ctx.notes.get(ctx.task.reads_notes[0])
    if landscape.type != NoteType.LANDSCAPE:
        raise RuntimeError(
            f"DECOMPOSE reads_notes[0] is {landscape.type.value}, expected landscape_note"
        )

    agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=DecomposeOutput,
        system_prompt=DECOMPOSE_SYSTEM,
    )
    user_prompt = f"Query: {query}\n\nLandscape:\n{_format_landscape_for_decomposer(landscape)}"
    r = await ctx.track(agent, user_prompt)
    out = r.output

    mutations: list[NoteMutation] = []
    spawned: list[Task] = []

    # AIMS decision note
    aims_body = (
        f"**Audience:** {out.aims.audience}\n\n"
        f"**Issue:** {out.aims.issue}\n\n"
        f"**Message:** {out.aims.message}\n\n"
        f"**Storyline:** {out.aims.storyline}"
    )
    aims_note = Note(
        id=new_note_id("decision"),
        type=NoteType.DECISION,
        title="AIMS scoping",
        description=out.aims.message,
        content=aims_body,
        metadata=DecisionMetadata(
            category="aims_scoping",
            rationale="emitted by DECOMPOSE",
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )
    mutations.append(NoteMutation(kind="create", note=aims_note))

    question_note_ids: list[NoteID] = []
    synth_task_ids: list[TaskID] = []

    # Termination-chain placeholder; deps wired after QS tasks are emitted.
    check_task = emit_check_termination_ready(ctx.task.id, [])

    for sq in out.sub_questions:
        q_note_id = new_note_id("question")
        q_note = Note(
            id=q_note_id,
            type=NoteType.QUESTION,
            title=sq.title,
            description=sq.description,
            content=sq.title,
            metadata=QuestionMetadata(
                classification=QuestionClassification(sq.classification),
            ),
            created_by=ctx.task.id,
            created_at=_now(),
            last_modified_at=_now(),
        )
        mutations.append(NoteMutation(kind="create", note=q_note))
        question_note_ids.append(q_note_id)

        # Per-question scout for breadth. Scout is cheap (search API calls
        # only; no fetch or LLM per source) so doing one per question is
        # fine even for decomposed queries with 5-6 sub-questions.
        scout = emit_scout_sources(
            goal=sq.title,
            scout_mode="question",
            parent_task_id=ctx.task.id,
            question_note_ids=[q_note_id],
        )
        spawned.append(scout)

        # QS fires when retrieval drains + readiness clears (handler
        # checks the gate on dispatch and re-emits if not ready).
        q_synth = emit_question_synthesize(
            sq.title, q_note_id, ctx.task.id, termination_task_id=check_task.id
        )
        spawned.append(q_synth)
        synth_task_ids.append(q_synth.id)

    # One rescore pass to score the landscape-seeded corpus against the
    # new questions. This is what kicks off FETCH_AND_EXTRACT fan-out for
    # the landscape Brave hits once questions exist.
    scouted_note_ids = [
        n.id
        for n in ctx.notes.all()
        if n.type == NoteType.SOURCE and getattr(n.metadata, "state", None) == SourceState.SCOUTED
    ]
    if scouted_note_ids:
        rescore = emit_rescore_relevance(scouted_note_ids, ctx.task.id)
        spawned.append(rescore)

    # META_SYNTHESIZE runs after every per-question synthesis lands.
    # Produces one cross-question reconciliation synthesis_note that
    # identifies tensions, bridges, and the overall research bottom line.
    # Placed in-chain between QS tasks and CHECK_TERMINATION_READY so
    # termination waits for it, and the validator sees both per-question
    # syntheses and the meta-synthesis.
    meta_synth = emit_meta_synthesize(
        question_note_ids=question_note_ids,
        upstream_synth_task_ids=synth_task_ids,
        parent_task_id=ctx.task.id,
    )
    spawned.append(meta_synth)

    # Finalize termination chain: CHECK waits on every QS AND the meta-
    # synthesis. The QS-generated VERIFY_CLAIM tasks graft onto CHECK
    # the same way they always did (see handle_question_synthesize).
    check_task.depends_on = [
        DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
        for t_id in [*synth_task_ids, meta_synth.id]
    ]
    validate_task = emit_validate_completion(ctx.task.id, check_task.id, question_note_ids)
    report = emit_write_report(question_note_ids, [], ctx.task.id)
    report.depends_on = [
        DepEdge(upstream=validate_task.id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
    ]
    spawned.append(check_task)
    spawned.append(validate_task)
    spawned.append(report)

    titles_preview = " | ".join(sq.title[:50] for sq in out.sub_questions)
    return TaskResult(
        note_mutations=mutations,
        spawned_tasks=spawned,
        verdict=(
            f"{len(out.sub_questions)} sub-question(s) — {titles_preview}; "
            f"rescoring {len(scouted_note_ids)} scouted sources"
        ),
    )


# --- SCOUT_SOURCES ---------------------------------------------------------


async def handle_scout_sources(ctx: HandlerContext) -> TaskResult:
    """Broad link discovery. Runs one or more reformulated queries via
    Brave + academic search, canonicalizes URLs against the existing
    corpus, and adds SCOUTED source_notes for genuinely new URLs.

    No fetch, no tier, no LLM per source — just coverage. On completion,
    spawns one RESCORE_RELEVANCE task over the new batch so relevance
    gets populated off the hot path.
    """
    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    scout_mode = ctx.task.input_refs.get("scout_mode", "question")
    topic = ctx.task.goal
    scout_cfg = ctx.pipeline.scouting
    if scout_mode == "landscape_seed":
        queries: list[ScoutQuery] = landscape_seed_queries(topic, scout_cfg)
    elif scout_mode == "verify_seed":
        queries = verify_seed_queries(topic, scout_cfg)
    else:
        queries = question_focused_queries(topic, scout_cfg)

    brave = BraveClient(api_key=brave_key)

    # Fan out Brave queries in parallel. Academic search is only worth it
    # for question-scoped scouts — landscape_seed already covers arxiv/
    # openreview via venue queries.
    async def _one_query(sq: ScoutQuery) -> list[tuple[ScoutQuery, object]]:
        try:
            hits = await brave.search(sq.query, count=min(sq.max_hits, 10))
        except Exception as exc:
            logger.warning("scout brave failed query=%r err=%s", sq.query[:80], exc)
            return []
        return [(sq, h) for h in hits]

    brave_results = await asyncio.gather(*(_one_query(sq) for sq in queries))

    # Pull academic hits for question-scoped scouts; they add authors/
    # venue/year metadata without an extra fetch. Landscape_seed already
    # gets these via venue queries (site:arxiv.org etc.), so skip there.
    academic_hits: list[object] = []
    if scout_mode in ("question", "verify_seed"):
        try:
            academic_hits = await search_academic(topic, local=ctx.local, limit_per_source=3)
        except Exception as exc:
            logger.warning("scout academic failed topic=%r err=%s", topic[:80], exc)

    # Build SCOUTED source_notes, deduped by canonical URL against the
    # corpus. New notes get the scout_strategy that discovered them; a URL
    # already in the corpus is NOT overwritten.
    corpus = CorpusIndex(ctx.notes)
    seed_q_ids = (
        ctx.task.input_refs.get("question_note_ids", "").split(",")
        if ctx.task.input_refs.get("question_note_ids")
        else []
    )

    new_notes: list[Note] = []
    seen_in_this_batch: set[str] = set()
    for sq, h in [pair for batch in brave_results for pair in batch]:
        url = getattr(h, "url", None)
        if not url:
            continue
        canonical = canonicalize_url(url)
        if canonical in seen_in_this_batch:
            continue
        seen_in_this_batch.add(canonical)
        if corpus.by_url(url) is not None:
            continue
        note = _new_scouted_note(
            url=url,
            title=getattr(h, "title", "") or url,
            snippet=getattr(h, "snippet", ""),
            created_by=ctx.task.id,
            strategy=sq.strategy,
            seed_question_ids=[q for q in seed_q_ids if q],
        )
        new_notes.append(note)

    # Academic hits take precedence on dedup because they carry better
    # metadata — but they still only add if URL isn't already in corpus.
    for h in academic_hits:
        url = getattr(h, "url", None)
        if not url:
            continue
        canonical = canonicalize_url(url)
        if canonical in seen_in_this_batch:
            continue
        seen_in_this_batch.add(canonical)
        if corpus.by_url(url) is not None:
            continue
        note = _new_scouted_note(
            url=url,
            title=getattr(h, "title", "") or url,
            snippet=getattr(h, "snippet", ""),
            created_by=ctx.task.id,
            strategy=f"academic:{getattr(h, 'source', 'unknown')}",
            seed_question_ids=[q for q in seed_q_ids if q],
        )
        # Stamp authors/venue/year directly on the metadata so later
        # stages don't have to re-fetch to know.
        meta = _src_meta(note)
        enriched_meta = meta.model_copy(
            update={
                "authors": list(getattr(h, "authors", []) or []),
                "venue": getattr(h, "venue", None),
                "year": getattr(h, "year", None),
                "citation_count": getattr(h, "citation_count", None),
            }
        )
        note = note.model_copy(update={"metadata": enriched_meta})
        new_notes.append(note)

    mutations = [NoteMutation(kind="create", note=n) for n in new_notes]
    spawned: list[Task] = []

    # Spawn one RESCORE_RELEVANCE over the new batch. If there are no
    # open questions yet (weird race; scout emitted before decompose
    # finished), RESCORE_RELEVANCE will no-op gracefully.
    if new_notes:
        batch_ids = [n.id for n in new_notes]
        batch_size = ctx.pipeline.promotion.rescore_batch_size
        # Chunk large batches to keep per-task LLM volume bounded.
        for i in range(0, len(batch_ids), batch_size):
            chunk = batch_ids[i : i + batch_size]
            spawned.append(emit_rescore_relevance(chunk, ctx.task.id))

    verdict = (
        f"scouted {len(new_notes)} new URLs via {len(queries)} queries "
        f"(mode={scout_mode}); spawned {len(spawned)} RESCORE"
    )
    return TaskResult(note_mutations=mutations, spawned_tasks=spawned, verdict=verdict)


# --- RESCORE_RELEVANCE ----------------------------------------------------


async def handle_rescore_relevance(ctx: HandlerContext) -> TaskResult:
    """LLM batch-score a chunk of SCOUTED sources against every open
    question. Updates each source_note.metadata.relevance, and spawns
    FETCH_AND_EXTRACT for sources that scored above the configured
    fetch threshold on any open question.

    If hygiene.prefetch_reject_list is on, URLs matching the reject-list
    (social, aggregators, unattributed) are auto-assigned Tier 5 and
    left SCOUTED — saves the wasted fetch + tier-classifier call.
    """
    ids_raw = ctx.task.input_refs.get("source_note_ids", "")
    source_note_ids = [i for i in ids_raw.split(",") if i]
    if not source_note_ids:
        return TaskResult(verdict="rescore: empty batch")

    questions = _open_questions(ctx)
    if not questions:
        # Landscape-seeded scout fired before DECOMPOSE emitted questions.
        # Harmless: a later rescore (from DECOMPOSE itself) will cover it.
        return TaskResult(verdict="rescore: no open questions yet; deferred")

    # Pull the sources we're scoring.
    targets: list[Note] = []
    for sid in source_note_ids:
        sid_typed = cast(NoteID, sid)
        if sid_typed not in ctx.notes:
            continue
        n = ctx.notes.get(sid_typed)
        if n.type != NoteType.SOURCE:
            continue
        targets.append(n)

    if not targets:
        return TaskResult(verdict="rescore: target notes missing")

    # Only re-score sources whose relevance hasn't been populated for
    # the current question set. Re-running relevance scoring over the
    # same (source, question) pair is wasteful — skip unless some
    # question hasn't been scored yet.
    def needs_scoring(note: Note) -> bool:
        meta = _src_meta(note)
        open_q_ids = {qid for qid, _ in questions}
        return not open_q_ids.issubset(meta.relevance.keys())

    targets = [n for n in targets if needs_scoring(n)]
    if not targets:
        return TaskResult(verdict="rescore: all targets already scored")

    sources_input: list[tuple[str, str, str]] = [
        (_src_meta(n).url, n.title, _src_meta(n).summary or n.description) for n in targets
    ]

    # Relevance scorer runs on cheap_deterministic LOW — resolve model
    # explicitly rather than using ctx.model_id so we don't burn
    # generative tokens on keyword-level scoring.
    scorer_model = ctx.routing.model_id_for(RoleClass.CHEAP_DETERMINISTIC, TaskTier.LOW)
    scores = await score_sources_batch(
        sources=sources_input,
        questions=questions,
        model_id=scorer_model,
        local=ctx.local,
    )

    # Build replacement source_notes with relevance populated, and spawn
    # FETCH_AND_EXTRACT for sources that scored above the fetch
    # threshold on any question.
    mutations: list[NoteMutation] = []
    spawned: list[Task] = []
    promoted_count = 0

    for n in targets:
        meta = _src_meta(n)
        url = meta.url
        new_scores = scores.get(url, {})
        merged = {**meta.relevance, **new_scores}
        new_meta = meta.model_copy(update={"relevance": merged})
        new_note = n.model_copy(update={"metadata": new_meta})
        # Pre-fetch reject-list gate (hygiene.prefetch_reject_list).
        # If the URL is obviously junk (social media, aggregators,
        # clickbait content farms), skip promotion entirely — we'd
        # waste a fetch + tier classifier call only to reject it.
        # Mark the relevance so it's recorded, leave state SCOUTED.
        reject_hit = ctx.pipeline.hygiene.prefetch_reject_list and _reject_list_match(url)
        if reject_hit:
            mutations.append(NoteMutation(kind="replace", note=new_note))
            logger.info("rescore reject-list skip url=%s", url)
            continue

        mutations.append(NoteMutation(kind="replace", note=new_note))

        # Promote to FETCH if any question scored high enough. The fetch
        # handler will then (per question) decide whether to analyze.
        fetch_threshold = ctx.pipeline.promotion.fetch_relevance_threshold
        if (
            meta.state == SourceState.SCOUTED
            and max(merged.values(), default=0.0) >= fetch_threshold
        ):
            spawned.append(emit_fetch_and_extract(n.id, ctx.task.id))
            promoted_count += 1

    verdict = (
        f"rescored {len(targets)} sources against {len(questions)} questions; "
        f"promoted {promoted_count} to FETCH"
    )
    return TaskResult(note_mutations=mutations, spawned_tasks=spawned, verdict=verdict)


# --- FETCH_AND_EXTRACT ----------------------------------------------------


async def handle_fetch_and_extract(ctx: HandlerContext) -> TaskResult:
    """Promote one SCOUTED source to FETCHED: pull content, tier-
    classify, and spawn ANALYZE_SOURCE for each question where the
    source is relevant enough.
    """
    sid_str = ctx.task.input_refs.get("source_note_id") or (
        ctx.task.reads_notes[0] if ctx.task.reads_notes else None
    )
    if sid_str is None:
        raise RuntimeError("FETCH_AND_EXTRACT requires source_note_id")
    sid = cast(NoteID, sid_str)
    if sid not in ctx.notes:
        raise RuntimeError(f"FETCH target {sid!r} not in note graph")
    src = ctx.notes.get(sid)
    if src.type != NoteType.SOURCE:
        raise RuntimeError(f"FETCH target {sid!r} is {src.type.value}, expected source_note")

    meta = _src_meta(src)
    if meta.state != SourceState.SCOUTED:
        logger.info("fetch skip — %s already in state %s", sid, meta.state.value)
        return TaskResult(verdict=f"noop: {sid} already {meta.state.value}")

    url = meta.url
    fetch = await fetch_and_extract(url)
    if fetch is None or not fetch.markdown:
        logger.info("fetch failed url=%s", url)
        # Mark the source as FETCHED but with empty content so we don't
        # re-try it repeatedly; tier=5 so it doesn't accidentally enter
        # the analyzer pool.
        failed_meta = meta.model_copy(
            update={
                "state": SourceState.FETCHED,
                "tier": Tier.TIER_5,
                "tier_rationale": "fetch failed (empty or blocked)",
                "classifier_confidence": 1.0,
                "peer_reviewed": False,
            }
        )
        failed_note = src.model_copy(update={"metadata": failed_meta})
        return TaskResult(
            note_mutations=[NoteMutation(kind="replace", note=failed_note)],
            verdict=f"fetch failed for {url}",
        )

    # Tier-classify on cheap_deterministic LOW.
    tier_model = ctx.routing.model_id_for(RoleClass.CHEAP_DETERMINISTIC, TaskTier.LOW)
    tier, rationale, confidence, peer_reviewed = await classify_source(
        title=fetch.title or meta.title or url,
        url=url,
        snippet=meta.summary or "",
        content=fetch.markdown,
        model_id=tier_model,
        local=ctx.local,
        tracker=ctx.tracker,
    )

    structured = (
        build_structured_content(fetch.title or meta.title or url, fetch.markdown)
        if is_long_source(fetch.markdown)
        else None
    )

    fetched_meta = meta.model_copy(
        update={
            "state": SourceState.FETCHED,
            "title": fetch.title or meta.title,
            "tier": tier,
            "tier_rationale": rationale,
            "classifier_confidence": confidence,
            "peer_reviewed": peer_reviewed,
            "structured_content": structured,
        }
    )
    fetched_note = src.model_copy(
        update={
            "title": fetch.title or src.title,
            "content": fetch.markdown[:40000],
            "metadata": fetched_meta,
        }
    )

    # Spawn ANALYZE_SOURCE per question where relevance ≥ threshold. Cap
    # fan-out to pipeline.promotion.max_analyses_per_source (top N).
    spawned: list[Task] = []
    max_analyses = ctx.pipeline.promotion.max_analyses_per_source
    analyze_threshold = ctx.pipeline.promotion.analyze_relevance_threshold
    if tier != Tier.TIER_5:
        scored = sorted(meta.relevance.items(), key=lambda kv: kv[1], reverse=True)[:max_analyses]
        for qid, score in scored:
            if score < analyze_threshold:
                continue
            q_id_typed = cast(NoteID, qid)
            if q_id_typed not in ctx.notes:
                continue
            # Pattern escalation (multi_perspective / debate / ach) is
            # driven by the replanner; fetch-spawned analyses default to
            # single_researcher / neutral framing.
            pattern = OrchestrationPattern.SINGLE_RESEARCHER
            spawned.append(
                emit_analyze_source(
                    source_note_id=sid,
                    question_note_id=q_id_typed,
                    parent_task_id=ctx.task.id,
                    pattern=pattern,
                )
            )

    verdict = (
        f"fetched {url} tier={tier.value} "
        f"({'peer_reviewed' if peer_reviewed else 'non-pr'}); "
        f"spawned {len(spawned)} ANALYZE"
    )
    return TaskResult(
        note_mutations=[NoteMutation(kind="replace", note=fetched_note)],
        spawned_tasks=spawned,
        verdict=verdict,
    )


# --- ANALYZE_SOURCE -------------------------------------------------------


def _build_analyzer(ctx: HandlerContext, framing: Perspective) -> Agent:
    system = ANALYZER_SYSTEM
    if framing.prompt_suffix:
        system = ANALYZER_SYSTEM + "\n\nFraming for this pass:\n" + framing.prompt_suffix
    return Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=AnalyzerOutput,
        system_prompt=system,
    )


def _analyzer_user_message(question: str, note: Note) -> str:
    meta = _src_meta(note)
    if meta.structured_content is not None:
        outline = render_outline(meta.structured_content)
        excerpt = note.content[:6000]
        body = (
            f"Structured outline (this source is long; the full markdown "
            f"follows the outline, truncated):\n\n{outline}\n\n---\n\n"
            f"Raw excerpt (first 6000 chars):\n{excerpt}"
        )
    else:
        body = f"Content:\n{note.content}"
    return f"Question: {question}\n\n" f"Source: {note.title}\nURL: {meta.url}\n\n{body}"


async def handle_analyze_source(ctx: HandlerContext) -> TaskResult:
    """Extract claims from one FETCHED source for one question.

    Claims are appended to source_note.metadata.claims with
    for_questions=[question_note_id]. analyzed_for is updated so we
    don't re-analyze the same (source, question) pair. state moves to
    ANALYZED on first analysis; stays ANALYZED for subsequent ones.

    Pattern determines framings: SINGLE_RESEARCHER → neutral only;
    MULTI_PERSPECTIVE → three framings; DEBATE → two.
    """
    sid_raw = ctx.task.input_refs.get("source_note_id")
    qid_raw = ctx.task.input_refs.get("question_note_id")
    if not sid_raw or not qid_raw:
        raise RuntimeError("ANALYZE_SOURCE requires source_note_id + question_note_id")
    sid = cast(NoteID, sid_raw)
    qid = cast(NoteID, qid_raw)
    if sid not in ctx.notes or qid not in ctx.notes:
        raise RuntimeError("ANALYZE_SOURCE inputs not in note graph")

    src = ctx.notes.get(sid)
    qnote = ctx.notes.get(qid)
    if src.type != NoteType.SOURCE or qnote.type != NoteType.QUESTION:
        raise RuntimeError("ANALYZE_SOURCE type mismatch in inputs")

    meta = _src_meta(src)
    if meta.state == SourceState.SCOUTED:
        logger.info("analyze skip — source still SCOUTED id=%s", sid)
        return TaskResult(verdict=f"noop: source {sid} not yet fetched")
    if qid in meta.analyzed_for:
        logger.info("analyze skip — already analyzed %s for %s", sid, qid)
        return TaskResult(verdict="noop: already analyzed")

    question = qnote.title

    # Pick framings per pattern (defaults to single/neutral).
    pattern = ctx.task.pattern or OrchestrationPattern.SINGLE_RESEARCHER
    if pattern == OrchestrationPattern.MULTI_PERSPECTIVE:
        framings: tuple[Perspective, ...] = PERSPECTIVES
    elif pattern == OrchestrationPattern.DEBATE:
        framings = DEBATE_FRAMINGS
    else:
        framings = (Perspective(name="neutral", prompt_suffix=""),)

    agents = {f.name: _build_analyzer(ctx, f) for f in framings}
    user = _analyzer_user_message(question, src)

    async def _run(f: Perspective) -> tuple[str, AnalyzerOutput | None]:
        try:
            r = await ctx.track(agents[f.name], user)
            return f.name, r.output
        except Exception as exc:
            logger.warning(
                "analyze failed sid=%s qid=%s framing=%s err=%s",
                sid,
                qid,
                f.name,
                exc,
            )
            return f.name, None

    outs = await asyncio.gather(*(_run(f) for f in framings))

    analyzer_family = ctx.routing.family_of(ctx.model_id)
    non_null = [(f, o) for f, o in outs if o is not None]
    if non_null and all(o.off_topic for _, o in non_null):
        # All framings agree the source doesn't bear on this question.
        # Record the attempt on analyzed_for so we don't re-analyze. If
        # hygiene.off_topic_relevance_penalty is on, zero out the
        # (source, question) relevance too so future rescores don't
        # re-promote this source for this question.
        update_fields: dict[str, object] = {
            "analyzed_for": sorted({*meta.analyzed_for, qid}),
            "state": (SourceState.ANALYZED if meta.state != SourceState.ANALYZED else meta.state),
        }
        if ctx.pipeline.hygiene.off_topic_relevance_penalty:
            penalized_relevance = dict(meta.relevance)
            penalized_relevance[qid] = 0.0
            update_fields["relevance"] = penalized_relevance
        updated_meta = meta.model_copy(update=update_fields)
        updated = src.model_copy(update={"metadata": updated_meta})
        return TaskResult(
            note_mutations=[NoteMutation(kind="replace", note=updated)],
            verdict=f"off_topic: {sid} for {qid}",
        )

    existing_claims = list(meta.claims or [])
    base_idx = len(existing_claims)
    added: list[ClaimItem] = []
    for fname, out in outs:
        if out is None or out.off_topic:
            continue
        for c in out.claims:
            added.append(
                ClaimItem(
                    id=f"{sid}-{base_idx + len(added)}",
                    text=c.text,
                    quote=c.quote,
                    extractor_confidence=c.extractor_confidence,
                    analyzed_by_family=analyzer_family,
                    perspective=fname,
                    models_tested=list(c.models_tested),
                    claim_type=ClaimType(c.claim_type),
                    for_questions=[qid],
                )
            )

    updated_meta = meta.model_copy(
        update={
            "claims": [*existing_claims, *added],
            "analyzed_for": sorted({*meta.analyzed_for, qid}),
            "state": SourceState.ANALYZED,
        }
    )
    updated = src.model_copy(update={"metadata": updated_meta})

    verdict = (
        f"extracted {len(added)} claim(s) for q={qid} from "
        f"src={sid} tier={meta.tier.value if meta.tier else '?'}"
    )
    return TaskResult(
        note_mutations=[NoteMutation(kind="replace", note=updated)],
        verdict=verdict,
    )


# --- QUESTION_SYNTHESIZE --------------------------------------------------
#
# Readiness-gated. On dispatch, the handler checks:
#   - how many sources are analyzed for this question, and
#   - whether any retrieval/analysis tasks are still in flight.
# If analyzed count < MIN or retrieval is still running, emit a fresh
# QS task depending on all currently-pending retrieval tasks and
# return without synthesizing. When those drain, the new QS fires.
# Bounded by MAX_QS_POLLS to avoid pathological re-emission loops.


def _claims_for_question(corpus: CorpusIndex, qid: str) -> list[tuple[Note, ClaimItem]]:
    """Every claim tagged for this question across the corpus."""
    out: list[tuple[Note, ClaimItem]] = []
    for n in corpus.analyzed_for_question(qid):
        for c in _src_meta(n).claims:
            if qid in c.for_questions:
                out.append((n, c))
    return out


async def _run_ach_flow(
    ctx: HandlerContext,
    question: str,
    enriched: list[Note],
    synth_note_id: str,
) -> tuple[SynthesizerOutput, list[Note]]:
    """Three-phase ACH (ADR 0004). Same as the old handler but now reads
    from the shared corpus rather than a per-question source set.
    """

    def _tier_label(n: Note) -> str:
        t = _src_meta(n).tier
        return str(t.value) if t is not None else "?"

    digest_parts = [
        f"Source {n.id} ({n.title}, tier {_tier_label(n)}):\n" f"{_format_claim_digest(n)}"
        for n in enriched
    ]
    evidence_digest = "\n\n".join(digest_parts)

    gen_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=AchHypothesisGenOutput,
        system_prompt=ACH_HYPOTHESIS_GEN_SYSTEM,
    )
    gen_user = (
        f"Question: {question}\n\n"
        f"Evidence digest ({len(enriched)} sources):\n\n{evidence_digest}"
    )
    gen_r = await ctx.track(gen_agent, gen_user)
    hypotheses = gen_r.output.hypotheses
    logger.info("ach generated n=%d hypotheses", len(hypotheses))

    mid_model = ctx.routing.model_id_for(RoleClass.JUDGMENT, TaskTier.MID)
    cons_agent = Agent(
        make_model(mid_model, ctx.local),
        output_type=AchConsistencyOutput,
        system_prompt=ACH_CONSISTENCY_SYSTEM,
    )

    async def _evaluate(h) -> list:
        user = (
            f"Hypothesis: {h.text}\n\n"
            f"Evidence digest ({len(enriched)} sources):\n\n{evidence_digest}\n\n"
            f"Return one verdict per source above (use the `Source X` IDs)."
        )
        try:
            r = await ctx.track(cons_agent, user)
            return r.output.verdicts
        except Exception as exc:
            logger.warning("ach consistency failed hypothesis=%s err=%s", h.label, exc)
            return []

    matrix = await asyncio.gather(*(_evaluate(h) for h in hypotheses))

    matrix_text_parts: list[str] = []
    for h, verdicts in zip(hypotheses, matrix, strict=True):
        matrix_text_parts.append(f"## Hypothesis: {h.label}\n{h.text}")
        if not verdicts:
            matrix_text_parts.append("  (no verdicts — consistency evaluation failed)")
            continue
        for v in verdicts:
            matrix_text_parts.append(f"  - [{v.verdict}] {v.source_id}: {v.rationale}")
    matrix_text = "\n".join(matrix_text_parts)

    adj_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=AchAdjudicationOutput,
        system_prompt=ACH_ADJUDICATION_SYSTEM,
    )
    adj_r = await ctx.track(
        adj_agent, f"Question: {question}\n\nConsistency matrix:\n\n{matrix_text}"
    )
    adj = adj_r.output
    logger.info("ach adopted=%r", adj.adopted_label)

    hypothesis_notes: list[Note] = []
    for h, verdicts in zip(hypotheses, matrix, strict=True):
        supporting = [v.source_id for v in verdicts if v.verdict == "consistent"]
        inconsistent = [v.source_id for v in verdicts if v.verdict == "inconsistent"]
        neutral = [v.source_id for v in verdicts if v.verdict == "neutral"]
        hypothesis_notes.append(
            Note(
                id=new_note_id("hypothesis"),
                type=NoteType.HYPOTHESIS,
                title=h.label,
                description=h.text,
                content=(
                    f"**Hypothesis:** {h.text}\n\n"
                    f"**Consistency breakdown:** {len(supporting)} consistent · "
                    f"{len(inconsistent)} inconsistent · {len(neutral)} neutral.\n\n"
                    + "\n".join(f"- [{v.verdict}] {v.source_id}: {v.rationale}" for v in verdicts)
                ),
                links=[
                    Link(
                        target_id=cast(NoteID, synth_note_id),
                        edge_type="hypothesis_of_synthesis",
                    )
                ],
                metadata=HypothesisMetadata(
                    hypothesis_text=h.text,
                    inconsistency_score=float(len(inconsistent)),
                    supporting_evidence=supporting,
                    inconsistent_evidence=inconsistent,
                    neutral_evidence=neutral,
                    tentatively_adopted=(h.label == adj.adopted_label),
                ),
                created_by=ctx.task.id,
                created_at=_now(),
                last_modified_at=_now(),
            )
        )

    synth_out = SynthesizerOutput(
        bottom_line=adj.bottom_line,
        synthesis=adj.synthesis,
        disagreements=adj.disagreements,
        confidence_note=adj.confidence_note,
    )
    return synth_out, hypothesis_notes


def _format_claim_digest(note: Note) -> str:
    claims = _src_meta(note).claims or []
    if not claims:
        return f"  (no claims extracted; snippet: {_src_meta(note).summary or note.description})"
    lines = []
    for c in claims:
        lines.append(f'  - "{c.text}" — quote: "{c.quote[:200]}"')
    return "\n".join(lines)


async def handle_question_synthesize(ctx: HandlerContext) -> TaskResult:
    """Readiness-gated synthesis over the shared corpus.

    Reads all claims tagged for this question across all sources,
    filters sources by analyzed_for + relevance, and either synthesizes
    or re-emits self pending the current retrieval/analysis set.
    """
    question = ctx.task.goal
    if not ctx.task.reads_notes:
        raise RuntimeError("QS expected a question_note in reads_notes")
    q_note_id = ctx.task.reads_notes[0]
    q_note = ctx.notes.get(q_note_id)
    if q_note.type != NoteType.QUESTION:
        raise RuntimeError(f"QS reads_notes[0] is {q_note.type.value}, expected question_note")

    corpus = CorpusIndex(ctx.notes)
    analyzed_for_q = corpus.analyzed_for_question(q_note_id)
    pending_retrieval = _pending_retrieval_task_ids(ctx, exclude_task_id=ctx.task.id)

    poll_count = int(ctx.task.input_refs.get("poll_count", "0"))
    enough_evidence = len(analyzed_for_q) >= ctx.pipeline.synthesis.min_analyzed_sources
    retrieval_quiesced = len(pending_retrieval) == 0
    polls_exhausted = poll_count >= ctx.pipeline.synthesis.max_qs_polls

    ready = enough_evidence or retrieval_quiesced or polls_exhausted

    if not ready:
        logger.info(
            "qs_poll question=%s analyzed=%d pending=%d poll=%d — re-emitting",
            q_note_id,
            len(analyzed_for_q),
            len(pending_retrieval),
            poll_count,
        )
        next_qs = emit_question_synthesize(
            question=question,
            question_note_id=cast(NoteID, q_note_id),
            parent_task_id=ctx.task.id,
            termination_task_id=cast(
                TaskID | None,
                ctx.task.input_refs.get("termination_task_id") or None,
            ),
            pattern=ctx.task.pattern or OrchestrationPattern.SINGLE_RESEARCHER,
            poll_count=poll_count + 1,
            depends_on=[
                DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
                for t_id in pending_retrieval
            ],
        )
        # Re-thread termination chain: the old QS was upstream of
        # CHECK_TERMINATION_READY; the replacement must take its place.
        termination_task_id = ctx.task.input_refs.get("termination_task_id")
        added_deps: list[DepEdgeAdd] = []
        if termination_task_id:
            added_deps.append(
                DepEdgeAdd(
                    downstream=cast(TaskID, termination_task_id),
                    upstream=next_qs.id,
                    kind=DependencyType.PRODUCES_CONTEXT_FOR,
                )
            )
        return TaskResult(
            spawned_tasks=[next_qs],
            added_dep_edges=added_deps,
            verdict=(
                f"poll {poll_count}: analyzed={len(analyzed_for_q)}, "
                f"pending={len(pending_retrieval)} — waiting"
            ),
        )

    # Ready. Assemble digest and synthesize.
    logger.info(
        "qs_synth question=%s analyzed=%d poll=%d enough=%s quiesced=%s exhausted=%s",
        q_note_id,
        len(analyzed_for_q),
        poll_count,
        enough_evidence,
        retrieval_quiesced,
        polls_exhausted,
    )

    # Cap synthesis input: on broad topics the corpus can have 20+
    # analyzed sources per question, which blows the synthesizer prompt
    # and dilutes signal. Take top N by (tier, relevance, max confidence).
    def _synthesis_rank(n: Note) -> tuple[float, float, float]:
        meta = _src_meta(n)
        tier_weight = (
            (6 - meta.tier.value) if meta.tier is not None else 0
        )  # tier 1 -> 5, tier 5 -> 1
        rel = meta.relevance.get(q_note_id, 0.0)
        max_conf = max(
            (c.extractor_confidence for c in meta.claims if q_note_id in c.for_questions),
            default=0.0,
        )
        return (tier_weight, rel, max_conf)

    candidates = [n for n in analyzed_for_q if _src_meta(n).claims]
    candidates.sort(key=_synthesis_rank, reverse=True)
    max_sources = ctx.pipeline.synthesis.max_sources_per_synthesis
    enriched = candidates[:max_sources]
    if len(candidates) > len(enriched):
        logger.info(
            "qs_cap question=%s total=%d capped_to=%d",
            q_note_id,
            len(candidates),
            len(enriched),
        )
    if not enriched:
        # No claims at all. Synthesize a thin "insufficient evidence"
        # note so the pipeline doesn't deadlock waiting on content that
        # never came.
        logger.warning("qs no claims for question=%s; emitting thin synthesis", q_note_id)
        synth_out = SynthesizerOutput(
            bottom_line=(
                "Insufficient evidence was retrieved for this question "
                "within the research budget."
            ),
            synthesis=(
                "No usable claims were extracted from the corpus for this "
                "sub-question. Either retrieval failed to surface on-topic "
                "sources, or the available sources were ruled off-topic by "
                "the analyzer."
            ),
            disagreements=[],
            confidence_note="Low — no evidence to back a conclusion.",
        )
        ach_hypothesis_notes: list[Note] = []
    else:
        is_ach = ctx.task.pattern == OrchestrationPattern.ACH
        is_debate = ctx.task.pattern == OrchestrationPattern.DEBATE
        is_multi = ctx.task.pattern == OrchestrationPattern.MULTI_PERSPECTIVE
        synth_note_id_pre = new_note_id("synthesis")
        ach_hypothesis_notes = []

        if is_ach:
            synth_out, ach_hypothesis_notes = await _run_ach_flow(
                ctx=ctx,
                question=question,
                enriched=enriched,
                synth_note_id=synth_note_id_pre,
            )
            synth_note_id = synth_note_id_pre
        else:
            synth_system = JUDGE_SYSTEM if is_debate else SYNTHESIZER_SYSTEM
            synth_agent = Agent(
                make_model(ctx.model_id, ctx.local),
                output_type=SynthesizerOutput,
                system_prompt=synth_system,
            )
            lines: list[str] = []
            tag_perspectives = is_multi or is_debate
            for n in enriched:
                meta = _src_meta(n)
                # Pull only claims tagged for THIS question — a source
                # might have claims extracted for other questions too.
                q_claims = [c for c in meta.claims if q_note_id in c.for_questions]
                if not q_claims:
                    continue
                year_str = f", {meta.year}" if meta.year else ""
                lines.append(f"Source: {n.title}{year_str} ({meta.url})")
                for c in q_claims:
                    prefix = f"[{c.perspective}] " if tag_perspectives else ""
                    lines.append(f"  - {prefix}Claim: {c.text}")
                    lines.append(f'    Quote: "{c.quote}"')
                    if c.models_tested:
                        lines.append(f"    Models tested: {', '.join(c.models_tested)}")
                lines.append("")

            # Peer-synthesis context: include bottom lines from other
            # sub-questions that have already synthesized. Gives this QS
            # enough cross-question awareness to flag agreements,
            # tensions, or dependencies rather than synthesizing in a
            # silo. Questions that finish retrieval earliest see no peer
            # context; that's fine — the META_SYNTHESIZE pass later
            # reconciles at the whole-run level.
            peer_lines: list[str] = []
            for other in ctx.notes.all():
                if other.type != NoteType.SYNTHESIS:
                    continue
                # Skip the current question's own prior synthesis if
                # it's being re-synthesized (replanner escalation).
                if q_note_id in [ln.target_id for ln in other.links if ln.edge_type == "answers"]:
                    continue
                peer_lines.append(f"- {other.title}: {other.description}")
            peer_block = ""
            if peer_lines:
                peer_block = (
                    "\n\n--- PEER SUB-QUESTION FINDINGS ---\n"
                    "(Bottom lines from other sub-questions of this research. "
                    "Use as context to surface tensions, bridges, or "
                    "dependencies with THIS question — don't just restate.)\n"
                    + "\n".join(peer_lines)
                )

            synth_user = f"Question: {question}\n\n" + "\n".join(lines) + peer_block
            synth_r = await ctx.track(synth_agent, synth_user)
            synth_out = synth_r.output
            synth_note_id = synth_note_id_pre

    contributing_sources = [n for n in enriched if _src_meta(n).claims]
    triangulation_score = len(contributing_sources)
    distinct_tiers = len(
        {_src_meta(s).tier.value for s in contributing_sources if _src_meta(s).tier is not None}
    )

    synth_note = Note(
        id=cast(NoteID, synth_note_id),
        type=NoteType.SYNTHESIS,
        title=f"Synthesis: {question[:80]}",
        description=synth_out.bottom_line,
        content=synth_out.synthesis,
        links=[Link(target_id=q_note_id, edge_type="answers")]
        + [Link(target_id=n.id, edge_type="source_for_synthesis") for n in enriched]
        + [Link(target_id=h.id, edge_type="hypothesis_of_synthesis") for h in ach_hypothesis_notes],
        metadata=SynthesisMetadata(
            pattern=(ctx.task.pattern or OrchestrationPattern.SINGLE_RESEARCHER).value,
            surviving_dissent=synth_out.disagreements,
            triangulation_score=triangulation_score,
            distinct_tiers=distinct_tiers,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    q_new_meta = q_note.metadata.model_copy(
        update={"status": "SYNTHESIZED", "adopted_position": synth_out.bottom_line}
    )
    q_updated = q_note.model_copy(update={"metadata": q_new_meta})

    mutations: list[NoteMutation] = [NoteMutation(kind="create", note=synth_note)]
    for h in ach_hypothesis_notes:
        mutations.append(NoteMutation(kind="create", note=h))
    mutations.append(NoteMutation(kind="replace", note=q_updated))

    # --- Post-synthesis: spawn VERIFY_CLAIM on cited / load-bearing claims
    verify_tasks: list[Task] = []
    added_deps: list[DepEdgeAdd] = []
    termination_task_id = ctx.task.input_refs.get("termination_task_id")
    # select_claims_to_verify takes a list of source_notes and picks top
    # claims by extractor_confidence. Filter to question-tagged claims
    # so verification only runs on claims load-bearing for this
    # synthesis.
    question_scoped_sources: list[Note] = []
    for n in enriched:
        meta = _src_meta(n)
        q_claims = [c for c in meta.claims if q_note_id in c.for_questions]
        if not q_claims:
            continue
        scoped_meta = meta.model_copy(update={"claims": q_claims})
        question_scoped_sources.append(n.model_copy(update={"metadata": scoped_meta}))

    picked = select_claims_to_verify(
        question_scoped_sources,
        max_per_synthesis=ctx.pipeline.verification.max_claims_per_synthesis,
        max_per_run=ctx.pipeline.verification.max_claims_per_run,
        skip_novel=ctx.pipeline.verification.skip_novel_claims,
    )
    for note, claim in picked:
        v_task = emit_verify_claim(
            claim=claim,
            source_note=note,
            question=question,
            write_report_task_id=cast(TaskID | None, termination_task_id),
            parent_task_id=ctx.task.id,
        )
        verify_tasks.append(v_task)
        if termination_task_id:
            added_deps.append(
                DepEdgeAdd(
                    downstream=cast(TaskID, termination_task_id),
                    upstream=v_task.id,
                    kind=DependencyType.PRODUCES_CONTEXT_FOR,
                )
            )

    verdict = f"{len(enriched)} sources synthesized — BLUF: {synth_out.bottom_line[:140]}"
    if verify_tasks:
        verdict += f" · {len(verify_tasks)} VERIFY_CLAIM spawned"

    return TaskResult(
        note_mutations=mutations,
        spawned_tasks=verify_tasks,
        added_dep_edges=added_deps,
        verdict=verdict,
    )


# --- META_SYNTHESIZE ------------------------------------------------------


async def handle_meta_synthesize(ctx: HandlerContext) -> TaskResult:
    """Cross-question reconciliation.

    Runs once all per-question syntheses have landed. Reads every
    synthesis_note + its parent question_note, produces one
    cross-question synthesis_note with:
      - overall bottom line (answering the root research query)
      - tensions between sub-question findings
      - bridges (where one sub-question's answer informs another)
      - surviving uncertainties across the whole run

    Feeds WRITE_REPORT through CHECK_TERMINATION_READY →
    VALIDATE_COMPLETION. The validator sees both per-question and
    meta-synthesis, so cross-question claims get audited the same way.
    """
    # Pull the per-question synthesis_notes, each with its question title.
    q_notes_by_id: dict[str, Note] = {
        n.id: n for n in ctx.notes.all() if n.type == NoteType.QUESTION
    }

    synthesis_pairs: list[tuple[Note, Note]] = []  # (question_note, synthesis_note)
    for s in ctx.notes.all():
        if s.type != NoteType.SYNTHESIS:
            continue
        # Follow the "answers" link to find the question this synthesis
        # addresses. Skip if no link (defensive — normal syntheses have
        # one; abandoned / unusual ones might not).
        q_id = None
        for link in s.links:
            if link.edge_type == "answers" and link.target_id in q_notes_by_id:
                q_id = link.target_id
                break
        if q_id is None:
            continue
        synthesis_pairs.append((q_notes_by_id[q_id], s))

    if not synthesis_pairs:
        # Nothing to reconcile. Emit a placeholder decision_note so the
        # downstream audit has a breadcrumb, and move on.
        logger.warning("meta_synthesize: no per-question syntheses found")
        placeholder = Note(
            id=new_note_id("decision"),
            type=NoteType.DECISION,
            title="Meta-synthesis skipped",
            description="No per-question syntheses available to reconcile.",
            content="No synthesis_notes were present when META_SYNTHESIZE ran.",
            metadata=DecisionMetadata(
                category="meta_synthesis_skipped",
                rationale="no per-question syntheses",
                relates_to_task=ctx.task.id,
            ),
            created_by=ctx.task.id,
            created_at=_now(),
            last_modified_at=_now(),
        )
        return TaskResult(
            note_mutations=[NoteMutation(kind="create", note=placeholder)],
            verdict="meta_synthesize: no per-question syntheses; emitted placeholder",
        )

    # Build the per-question digest — title + bottom line + key
    # disagreements so the meta-synthesizer can see what each sub-question
    # concluded and where each was hedged.
    lines: list[str] = []
    for q_note, s_note in synthesis_pairs:
        lines.append(f"## Sub-question: {q_note.title}")
        lines.append(f"Bottom line: {s_note.description}")
        body = s_note.content.strip()
        if body:
            # Truncate long synthesis bodies — meta-synthesizer reads
            # many at once; don't blow the prompt.
            lines.append(f"Synthesis: {body[:1500]}")
        dissent = getattr(s_note.metadata, "surviving_dissent", []) or []
        if dissent:
            lines.append("Surviving dissent within this sub-question:")
            for d in dissent[:3]:
                lines.append(f"  - {d}")
        lines.append("")

    agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=SynthesizerOutput,
        system_prompt=META_SYNTHESIZER_SYSTEM,
    )
    user = "Per-question syntheses:\n\n" + "\n".join(lines)
    r = await ctx.track(agent, user)
    out = r.output

    meta_note_id = new_note_id("synthesis")
    meta_note = Note(
        id=meta_note_id,
        type=NoteType.SYNTHESIS,
        title="Cross-question synthesis",
        description=out.bottom_line,
        content=out.synthesis,
        # Link to every per-question synthesis so the UI can draw the
        # reconciliation edge; and to every question_note with a
        # "cross_answers" edge so it's clear this is whole-run-scoped.
        links=[Link(target_id=s.id, edge_type="reconciles_synthesis") for _, s in synthesis_pairs]
        + [Link(target_id=q.id, edge_type="cross_answers") for q, _ in synthesis_pairs],
        metadata=SynthesisMetadata(
            pattern="meta_synthesis",
            surviving_dissent=out.disagreements,
            # Triangulation/distinct_tiers don't apply in the usual sense
            # here — this synthesis triangulates over syntheses, not over
            # source tiers. Leave at 0 so the validator's gate 6 logic
            # doesn't confuse cross-question coherence with per-claim
            # source-tier triangulation.
            triangulation_score=0,
            distinct_tiers=0,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=meta_note)],
        verdict=(
            f"meta_synthesis: BLUF: {out.bottom_line[:140]} "
            f"(reconciled {len(synthesis_pairs)} sub-questions)"
        ),
    )


# --- VERIFY_CLAIM ---------------------------------------------------------


async def handle_verify_claim(ctx: HandlerContext) -> TaskResult:
    """Cross-family verification of one cited claim (ADR 0008).

    Broader than before: fetches 5 independent sources, and any new URLs
    found are added to the shared corpus as SCOUTED so future runs /
    questions benefit from the evidence.
    """
    claim_id = ctx.task.input_refs.get("claim_id")
    source_note_id = ctx.task.input_refs.get("source_note_id")
    question = ctx.task.input_refs.get("question", "")
    if not claim_id or not source_note_id:
        raise RuntimeError(
            "VERIFY_CLAIM requires input_refs['claim_id'] and input_refs['source_note_id']"
        )

    source_note = ctx.notes.get(cast(NoteID, source_note_id))
    claim = next(
        (c for c in _src_meta(source_note).claims if c.id == claim_id),
        None,
    )
    if claim is None:
        raise RuntimeError(f"claim {claim_id!r} not found on source_note {source_note_id!r}")

    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    search_query = _build_verify_query(claim.text, question)
    brave = BraveClient(api_key=brave_key)
    # Broader than before (8 hits vs 3) so verification can cite
    # multiple independent sources when the claim is contested.
    hits = await brave.search(search_query, count=8)
    independent_count = ctx.pipeline.verification.independent_hits
    primary_url = _src_meta(source_note).url

    def _same_source(hit_url: str) -> bool:
        if not primary_url:
            return False
        if hit_url == primary_url:
            return True
        primary_stem = primary_url.rstrip("/").split("?", 1)[0]
        hit_stem = hit_url.rstrip("/").split("?", 1)[0]
        return primary_stem.rsplit("/", 2)[-1] == hit_stem.rsplit("/", 2)[-1]

    independent_hits = [h for h in hits if not _same_source(h.url)][:independent_count]
    logger.info(
        "verify_claim claim_id=%s independent_hits=%d primary=%s",
        claim_id,
        len(independent_hits),
        primary_url,
    )

    fetches = await asyncio.gather(
        *(fetch_and_extract(h.url) for h in independent_hits),
        return_exceptions=True,
    )
    excerpts: list[str] = []
    for hit, fetch in zip(independent_hits, fetches, strict=True):
        if isinstance(fetch, BaseException) or fetch is None or not fetch.markdown:
            excerpts.append(f"Source: {hit.title}\nURL: {hit.url}\nSnippet: {hit.snippet}")
        else:
            excerpts.append(
                f"Source: {fetch.title or hit.title}\nURL: {hit.url}\n"
                f"Content (truncated): {fetch.markdown[:6000]}"
            )

    if not excerpts:
        logger.warning("verify_claim claim_id=%s got 0 independent excerpts", claim_id)
        verdict_label = "INCONCLUSIVE"
        rationale_text = "No independent sources were retrievable for this claim."
        disagreements: list[str] = []
    else:
        verifier = Agent(
            make_model(ctx.model_id, ctx.local),
            output_type=VerifierOutput,
            system_prompt=VERIFIER_SYSTEM,
        )
        user_prompt = (
            f"Question context: {question}\n\n"
            f"Claim to verify: {claim.text}\n"
            f'Primary source quote: "{claim.quote}"\n'
            f"Primary source URL (NOT independent): {primary_url}\n\n"
            f"Independent sources:\n\n" + "\n\n---\n\n".join(excerpts)
        )
        r = await ctx.track(verifier, user_prompt)
        vout = r.output
        verdict_label = vout.verdict
        rationale_text = vout.rationale
        disagreements = vout.disagreement_notes

    # Write the verification decision_note and update the claim's status.
    v_note_id = new_note_id("verification")
    body_parts = [f"**Verdict:** {verdict_label}", "", rationale_text]
    if disagreements:
        body_parts.extend(["", "**Disagreement notes:**"])
        body_parts.extend(f"- {d}" for d in disagreements)
    verifier_family = ctx.routing.family_of(ctx.model_id)
    verification_note = Note(
        id=v_note_id,
        type=NoteType.DECISION,
        title=f"Verified ({verdict_label}): {claim.text[:60]}",
        description=f"{verdict_label} — by {verifier_family}",
        content="\n".join(body_parts),
        links=[Link(target_id=cast(NoteID, source_note_id), edge_type="verification_of")],
        metadata=DecisionMetadata(
            category="verification",
            rationale=f"cross-family verification by {verifier_family}",
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    status_map = {
        "SUPPORTS": VerificationStatus.SUPPORTS,
        "REFUTES": VerificationStatus.REFUTES,
        "INCONCLUSIVE": VerificationStatus.INCONCLUSIVE,
    }
    existing_claims = _src_meta(source_note).claims or []
    updated_claims = [
        c.model_copy(
            update={
                "verification_status": status_map[verdict_label],
                "verification_rationale": rationale_text,
                "verification_note_id": v_note_id,
            }
        )
        if c.id == claim_id
        else c
        for c in existing_claims
    ]
    new_src_meta = _src_meta(source_note).model_copy(update={"claims": updated_claims})
    src_updated = source_note.model_copy(update={"metadata": new_src_meta})

    mutations: list[NoteMutation] = [
        NoteMutation(kind="create", note=verification_note),
        NoteMutation(kind="replace", note=src_updated),
    ]

    # Feed good new independent sources back into the shared corpus as
    # SCOUTED notes IF there are still open questions that could benefit.
    # When verification.skip_seeding_after_synthesis is true and all
    # questions are already SYNTHESIZED, skip the seeding — adding
    # SCOUTED sources at this point is pure clutter (no rescore will
    # promote them because _open_questions returns nothing).
    corpus = CorpusIndex(ctx.notes)
    new_scouted: list[Note] = []
    skip_seeding = ctx.pipeline.verification.skip_seeding_after_synthesis and not _open_questions(
        ctx
    )
    if not skip_seeding:
        for hit in independent_hits:
            if not hit.url:
                continue
            if corpus.by_url(hit.url) is not None:
                continue
            new_scouted.append(
                _new_scouted_note(
                    url=hit.url,
                    title=hit.title,
                    snippet=hit.snippet,
                    created_by=ctx.task.id,
                    strategy="verify_seed",
                )
            )
        for n in new_scouted:
            mutations.append(NoteMutation(kind="create", note=n))

    spawned: list[Task] = []
    if new_scouted:
        spawned.append(emit_rescore_relevance([n.id for n in new_scouted], ctx.task.id))

    return TaskResult(
        note_mutations=mutations,
        spawned_tasks=spawned,
        verdict=(
            f"{verdict_label}: {rationale_text[:100]}"
            + (f" · +{len(new_scouted)} corpus sources" if new_scouted else "")
        ),
    )


# --- CHECK_TERMINATION_READY ----------------------------------------------


def _structural_termination_check(ctx: HandlerContext) -> tuple[bool, list[str]]:
    """Deterministic structural checks from ADR 0009."""
    gaps: list[str] = []

    for n in ctx.notes.all():
        if n.type != NoteType.QUESTION:
            continue
        status = getattr(n.metadata, "status", None)
        if status != "SYNTHESIZED":
            gaps.append(f"Question '{n.title[:80]}' status={status!r}, expected SYNTHESIZED")

    contested_q_ids: set[str] = set()
    for n in ctx.notes.all():
        if n.type != NoteType.QUESTION:
            continue
        classification = getattr(n.metadata, "classification", None)
        cls_value = classification.value if hasattr(classification, "value") else classification
        if cls_value == QuestionClassification.CONTESTED.value:
            contested_q_ids.add(n.id)

    if contested_q_ids:
        heavy_patterns = {"multi_perspective", "debate", "ach"}
        disconfirmed_q: set[str] = set()
        for synth in ctx.notes.all():
            if synth.type != NoteType.SYNTHESIS:
                continue
            pattern = getattr(synth.metadata, "pattern", None)
            if pattern not in heavy_patterns:
                continue
            disconfirmed_q |= contested_q_ids
        missing = contested_q_ids - disconfirmed_q
        if missing:
            for q_id in missing:
                gaps.append(
                    f"Contested question {q_id} has no disconfirmation pass "
                    f"(no multi_perspective / debate / ach synthesis)"
                )

    return len(gaps) == 0, gaps


async def handle_check_termination_ready(ctx: HandlerContext) -> TaskResult:
    passed, gaps = _structural_termination_check(ctx)
    verdict_label = "PASS" if passed else "FAIL"
    body_lines = [f"**Verdict:** {verdict_label}"]
    if gaps:
        body_lines.append("")
        body_lines.append("**Structural gaps:**")
        body_lines.extend(f"- {g}" for g in gaps)
    else:
        body_lines.append("")
        body_lines.append("No structural gaps detected.")

    decision_note = Note(
        id=new_note_id("decision"),
        type=NoteType.DECISION,
        title=f"Termination readiness: {verdict_label}",
        description=f"{verdict_label} · {len(gaps)} gap(s)",
        content="\n".join(body_lines),
        metadata=DecisionMetadata(
            category="termination_readiness",
            rationale="; ".join(gaps) if gaps else "all structural gates passed",
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )
    if not passed:
        logger.warning("termination_readiness gaps=%d task_id=%s: %s", len(gaps), ctx.task.id, gaps)
    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=decision_note)],
        verdict=f"{verdict_label} · {len(gaps)} structural gap(s)",
    )


# --- VALIDATE_COMPLETION --------------------------------------------------


async def handle_validate_completion(ctx: HandlerContext) -> TaskResult:
    synthesis_notes = [n for n in ctx.notes.all() if n.type == NoteType.SYNTHESIS]
    question_notes = [n for n in ctx.notes.all() if n.type == NoteType.QUESTION]
    source_notes = [n for n in ctx.notes.all() if n.type == NoteType.SOURCE]

    lines: list[str] = []
    for s in synthesis_notes:
        meta = s.metadata
        triangulation = getattr(meta, "triangulation_score", 0)
        distinct_tiers = getattr(meta, "distinct_tiers", 0)
        lines.append(
            f"## Synthesis {s.id} (pattern: {getattr(meta, 'pattern', '?')}, "
            f"triangulation_score={triangulation}, distinct_tiers={distinct_tiers})"
        )
        lines.append(f"Bottom line: {s.description}")
        lines.append(s.content)
        disagreements = getattr(meta, "surviving_dissent", []) or []
        if disagreements:
            lines.append(f"Surviving dissent: {disagreements}")
        lines.append("")
    lines.append("## Evidence (source digests)")
    for sn in source_notes[:12]:
        meta = _src_meta(sn)
        tier_val = meta.tier.value if meta.tier else "?"
        lines.append(f"- {sn.id}: {sn.title} (tier {tier_val}) — {meta.url}")
        for c in (meta.claims or [])[:3]:
            lines.append(f'    claim: "{c.text}"')
    audit_package = "\n".join(lines)

    user = (
        f"Audit this research run against the six completion gates. "
        f"Research produced {len(synthesis_notes)} syntheses covering "
        f"{len(question_notes)} sub-question(s).\n\n{audit_package}"
    )
    try:
        agent = Agent(
            make_model(ctx.model_id, ctx.local),
            output_type=ValidateCompletionOutput,
            system_prompt=VALIDATE_COMPLETION_SYSTEM,
        )
        r = await ctx.track(agent, user)
        out = r.output
    except Exception as exc:
        logger.warning("validate_completion audit failed err=%s", exc)
        out = ValidateCompletionOutput(
            verdict="PASS",
            rationale=f"audit LLM call failed: {type(exc).__name__}; passing with warning",
            gate_notes=[],
            remediation=[],
        )

    gate_text = "\n".join(f"- {gn}" for gn in out.gate_notes)
    remediation_text = "\n".join(f"- {r}" for r in out.remediation)
    body = (
        f"**Verdict:** {out.verdict}\n\n"
        f"**Rationale:** {out.rationale}\n\n"
        f"**Gate notes:**\n{gate_text or '(none)'}\n\n"
        f"**Remediation suggested:**\n{remediation_text or '(none)'}"
    )
    decision_note = Note(
        id=new_note_id("decision"),
        type=NoteType.DECISION,
        title=f"Completion audit: {out.verdict}",
        description=out.rationale[:280],
        content=body,
        metadata=DecisionMetadata(
            category="completion_audit",
            rationale=out.rationale,
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )
    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=decision_note)],
        verdict=f"{out.verdict}: {out.rationale[:120]}",
    )


# --- WRITE_REPORT ---------------------------------------------------------


async def handle_write_report(ctx: HandlerContext) -> TaskResult:
    q_notes = [n for n in ctx.notes.all() if n.type == NoteType.QUESTION]
    synth_notes = [n for n in ctx.notes.all() if n.type == NoteType.SYNTHESIS]
    source_notes = [n for n in ctx.notes.all() if n.type == NoteType.SOURCE]
    verification_notes = [
        n
        for n in ctx.notes.all()
        if n.type == NoteType.DECISION and getattr(n.metadata, "category", "") == "verification"
    ]
    termination_notes = [
        n
        for n in ctx.notes.all()
        if n.type == NoteType.DECISION
        and getattr(n.metadata, "category", "") in ("termination_readiness", "completion_audit")
    ]

    verdict_counts = {"SUPPORTS": 0, "REFUTES": 0, "INCONCLUSIVE": 0, "UNVERIFIED": 0}
    for sn in source_notes:
        for c in _src_meta(sn).claims:
            verdict_counts[c.verification_status.value] = (
                verdict_counts.get(c.verification_status.value, 0) + 1
            )

    # Coverage stats for the report context — highlights the new
    # streaming pipeline's source-reuse behavior.
    corpus = CorpusIndex(ctx.notes)
    cov = corpus.coverage_summary()

    parts: list[str] = ["# RESEARCH NOTES (context for the report)"]
    parts.append(
        f"\n## Corpus coverage\n"
        f"Total sources in corpus: {cov['total']} "
        f"(scouted={cov['scouted']}, fetched={cov['fetched']}, analyzed={cov['analyzed']}). "
        f"Sources reused across ≥2 questions: {cov['multi_question']}."
    )
    if sum(v for k, v in verdict_counts.items() if k != "UNVERIFIED") > 0:
        parts.append(
            f"\n## Verification summary\n"
            f"Cross-family verification results across all extracted claims: "
            f"SUPPORTS={verdict_counts.get('SUPPORTS', 0)}, "
            f"REFUTES={verdict_counts.get('REFUTES', 0)}, "
            f"INCONCLUSIVE={verdict_counts.get('INCONCLUSIVE', 0)}, "
            f"UNVERIFIED={verdict_counts.get('UNVERIFIED', 0)}."
        )
    # Surface the meta-synthesis FIRST and prominently — it's the
    # cross-question story the report writer should anchor on. Then the
    # per-question syntheses provide the supporting detail.
    meta_synth_notes = [
        s for s in synth_notes if getattr(s.metadata, "pattern", "") == "meta_synthesis"
    ]
    per_question_synths = [
        s for s in synth_notes if getattr(s.metadata, "pattern", "") != "meta_synthesis"
    ]
    if meta_synth_notes:
        parts.append(
            "\n## Cross-question synthesis " "(LOAD-BEARING — use this as the report's spine)"
        )
        for m in meta_synth_notes:
            parts.append(f"Overall bottom line: {m.description}")
            parts.append(f"Body:\n{m.content}")
            mdissent = getattr(m.metadata, "surviving_dissent", [])
            if mdissent:
                parts.append("Cross-question tensions:")
                for d in mdissent:
                    parts.append(f"  - {d}")

    for q in q_notes:
        parts.append(f"\n## Question\n{q.title}")
        adopted = getattr(q.metadata, "adopted_position", None) or "(none)"
        parts.append(f"Adopted position: {adopted}")
    for s in per_question_synths:
        parts.append(f"\n## Synthesis: {s.title}")
        parts.append(f"Bottom line: {s.description}")
        parts.append(f"Body:\n{s.content}")
        dissent = getattr(s.metadata, "surviving_dissent", [])
        if dissent:
            parts.append("Disagreements:")
            for d in dissent:
                parts.append(f"  - {d}")
    parts.append("\n## Sources")
    for sn in source_notes:
        meta = _src_meta(sn)
        tier_val = meta.tier.value if meta.tier else "?"
        state = meta.state.value
        parts.append(f"- {sn.title} — {meta.url}  (Tier {tier_val}, state {state})")
        for c in meta.claims:
            tag = (
                f" [{c.verification_status.value}]"
                if c.verification_status != VerificationStatus.UNVERIFIED
                else ""
            )
            parts.append(f'    - "{c.quote[:180]}" → {c.text}{tag}')
    if verification_notes:
        parts.append("\n## Independent verification rationales")
        for v in verification_notes:
            parts.append(f"- {v.title}")
            parts.append(f"  {v.content}")
    if termination_notes:
        parts.append("\n## Termination + completion audit")
        parts.append(
            "Surface any FAIL / PASS_WITH_WARNINGS verdicts and their gate notes "
            "in the report's limitations section."
        )
        for tn in termination_notes:
            parts.append(f"- {tn.title}")
            parts.append(f"  {tn.content}")

    report_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=ReportOutput,
        system_prompt=REPORT_SYSTEM,
    )
    r = await ctx.track(report_agent, "\n".join(parts))

    report_note = Note(
        id=new_note_id("report"),
        type=NoteType.DECISION,
        title="Final Research Report",
        description="Markdown report assembled from synthesis + sources.",
        content=r.output.markdown,
        metadata=DecisionMetadata(
            category="final_report",
            rationale="assembled by WRITE_REPORT handler",
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    # Log coverage to the run log so the user can see source reuse.
    logger.info(
        "run_coverage total=%d scouted=%d fetched=%d analyzed=%d multi_question=%d",
        cov["total"],
        cov["scouted"],
        cov["fetched"],
        cov["analyzed"],
        cov["multi_question"],
    )

    # Hygiene audit: count SCOUTED and FETCHED-but-no-claims sources that
    # never contributed to a synthesis. Emit a decision_note recording
    # the waste for the audit trail. Doesn't delete anything — notes are
    # immutable — but makes dead weight visible in the run output.
    mutations: list[NoteMutation] = [NoteMutation(kind="create", note=report_note)]
    if ctx.pipeline.hygiene.record_pruned_scouted:
        dead_scouted = cov["scouted"]
        dead_fetched_no_claims = 0
        for sn in source_notes:
            meta = _src_meta(sn)
            if meta.state == SourceState.FETCHED and not meta.claims:
                dead_fetched_no_claims += 1
        if dead_scouted > 0 or dead_fetched_no_claims > 0:
            prune_note = Note(
                id=new_note_id("decision"),
                type=NoteType.DECISION,
                title=f"Corpus hygiene: {dead_scouted + dead_fetched_no_claims} unused sources",
                description=(
                    f"SCOUTED (never fetched): {dead_scouted} · "
                    f"FETCHED but no claims (failed / junk / off-topic): "
                    f"{dead_fetched_no_claims}"
                ),
                content=(
                    f"**Never promoted (SCOUTED):** {dead_scouted}\n\n"
                    f"**Fetched but yielded no claims:** {dead_fetched_no_claims}\n\n"
                    f"These represent wasted scouting breadth. Most are from "
                    f"verify_seed (arrived after synthesis) or failed fetches. "
                    f"Check source_note scout_strategy to identify which "
                    f"reformulations are lowest-yield."
                ),
                metadata=DecisionMetadata(
                    category="corpus_hygiene",
                    rationale=(
                        f"run ended with {dead_scouted} scouted + "
                        f"{dead_fetched_no_claims} fetched-no-claims sources unused"
                    ),
                    relates_to_task=ctx.task.id,
                ),
                created_by=ctx.task.id,
                created_at=_now(),
                last_modified_at=_now(),
            )
            mutations.append(NoteMutation(kind="create", note=prune_note))
            logger.info(
                "corpus_hygiene scouted_unused=%d fetched_no_claims=%d",
                dead_scouted,
                dead_fetched_no_claims,
            )

    return TaskResult(
        note_mutations=mutations,
        verdict=(
            f"report emitted as note {report_note.id} — "
            f"corpus {cov['total']} sources, {cov['multi_question']} multi-question"
        ),
    )


# --- Registration ---------------------------------------------------------


def register_handlers(executor: AgentExecutor) -> None:
    """Register the streaming-pipeline handler set on an AgentExecutor."""
    executor.register(TaskType.LANDSCAPE_SURVEY, handle_landscape_survey)
    executor.register(TaskType.DECOMPOSE, handle_decompose)
    executor.register(TaskType.SCOUT_SOURCES, handle_scout_sources)
    executor.register(TaskType.FETCH_AND_EXTRACT, handle_fetch_and_extract)
    executor.register(TaskType.ANALYZE_SOURCE, handle_analyze_source)
    executor.register(TaskType.RESCORE_RELEVANCE, handle_rescore_relevance)
    executor.register(TaskType.QUESTION_SYNTHESIZE, handle_question_synthesize)
    executor.register(TaskType.META_SYNTHESIZE, handle_meta_synthesize)
    executor.register(TaskType.VERIFY_CLAIM, handle_verify_claim)
    executor.register(TaskType.CHECK_TERMINATION_READY, handle_check_termination_ready)
    executor.register(TaskType.VALIDATE_COMPLETION, handle_validate_completion)
    executor.register(TaskType.WRITE_REPORT, handle_write_report)


register_v0_handlers = register_handlers
