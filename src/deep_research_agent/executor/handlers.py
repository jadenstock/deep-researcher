"""v0 task-type handlers.

Each handler matches `HandlerFn` — async (HandlerContext) -> TaskResult.
Registered on an AgentExecutor via `register_v0_handlers`.

v0 scope (per design/phase-1-initial-design/10-implementation-plan.md):

    DECOMPOSE             Trivial — creates one question_note from the raw
                          query and spawns QUESTION_SYNTHESIZE + WRITE_REPORT.
                          Real AIMS scoping and classification land in v1.

    QUESTION_SYNTHESIZE   Fat handler: runs the single_researcher flow
                          imperatively (Brave search → HTML fetch →
                          per-source analyzer → cross-source synthesizer).
                          Split into fine-grained tasks in v2 when the
                          replanner needs the sub-DAG visible.

    WRITE_REPORT          Assembles the final markdown report from the
                          note graph and emits it as a decision_note
                          tagged category="final_report".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..patterns.ach import (
    ACH_ADJUDICATION_SYSTEM,
    ACH_CONSISTENCY_SYSTEM,
    ACH_HYPOTHESIS_GEN_SYSTEM,
)
from ..patterns.debate import DEBATE_FRAMINGS
from ..patterns.maker_checker import emit_verify_claim, select_claims_to_verify
from ..patterns.multi_perspective import PERSPECTIVES, Perspective
from ..patterns.single_researcher import (
    emit_decompose,
    emit_question_synthesize,
    emit_write_report,
)
from ..retrieval import (
    BraveClient,
    build_structured_content,
    fetch_and_extract,
    is_long_source,
    render_outline,
    rerank,
    search_academic,
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
    PositionItem,
    QuestionMetadata,
    SourceNoteMetadata,
    SynthesisMetadata,
    ThemeItem,
)
from ..schemas.enums import (
    DependencyType,
    NoteType,
    OrchestrationPattern,
    QuestionClassification,
    RoleClass,
    TaskTier,
    TaskType,
    VerificationStatus,
)
from ..tiering.classifier import classify_source
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
    VerifierOutput,
)
from .prompts import (
    ANALYZER_SYSTEM,
    DECOMPOSE_SYSTEM,
    JUDGE_SYSTEM,
    LANDSCAPE_SYSTEM,
    REPORT_SYSTEM,
    SYNTHESIZER_SYSTEM,
    VERIFIER_SYSTEM,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


# --- LANDSCAPE_SURVEY -------------------------------------------------------


async def handle_landscape_survey(ctx: HandlerContext) -> TaskResult:
    """Phase 1: broad search + one batched LLM pass over snippets to map the
    territory before decomposition (ADR 0001).

    v1 simplification: landscape uses Brave snippets only (no fetches). Real
    stub source_notes per ADR 0001 land in v2 when they can feed forward into
    the deep-research phase to avoid redundant refetches.
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
    r = await agent.run(f"Query: {query}\n\nSearch hit snippets:\n\n{snippets_text}")
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

    decompose = emit_decompose(query, landscape_id, ctx.task.id)
    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=landscape_note)],
        spawned_tasks=[decompose],
        verdict=(
            f"landscape_note {landscape_id}: "
            f"{len(out.themes)} themes, {len(out.positions)} positions"
        ),
    )


# --- DECOMPOSE --------------------------------------------------------------


def _format_landscape_for_decomposer(landscape: Note) -> str:
    meta = landscape.metadata
    parts: list[str] = []
    parts.append(f"Summary: {landscape.description}")
    parts.append("")
    parts.append("Discussion:")
    parts.append(landscape.content)
    if meta.themes:
        parts.append("")
        parts.append("Themes:")
        for t in meta.themes:
            parts.append(f"  - {t.name}: {t.description}")
    if meta.positions:
        parts.append("")
        parts.append("Positions surfaced:")
        for p in meta.positions:
            parts.append(f"  - {p.label}: {p.description}")
    if meta.under_covered_areas:
        parts.append("")
        parts.append("Under-covered areas:")
        for a in meta.under_covered_areas:
            parts.append(f"  - {a}")
    return "\n".join(parts)


async def handle_decompose(ctx: HandlerContext) -> TaskResult:
    """Evidence-grounded decomposition (TDD §5.2).

    Reads the landscape_note to classify sub-questions grounded in what
    the landscape actually surfaced (ADR 0001). Emits AIMS as a
    decision_note, one question_note per sub-question, one
    QUESTION_SYNTHESIZE task per sub-question, and one WRITE_REPORT
    depending on all syntheses.
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
    user_prompt = f"Query: {query}\n\n" f"Landscape:\n{_format_landscape_for_decomposer(landscape)}"
    r = await agent.run(user_prompt)
    out = r.output

    mutations: list[NoteMutation] = []
    spawned: list = []

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

    question_note_ids = []
    synth_task_ids = []

    # Build the WRITE_REPORT task first so its id can be threaded into
    # each QUESTION_SYNTHESIZE via input_refs; QS handlers need it to
    # graft VERIFY_CLAIM tasks onto the report's dependency list.
    report = emit_write_report([], [], ctx.task.id)

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

        q_synth = emit_question_synthesize(
            sq.title, q_note_id, ctx.task.id, write_report_task_id=report.id
        )
        spawned.append(q_synth)
        synth_task_ids.append(q_synth.id)

    # Finalize report: points at all question_notes + depends on every
    # QUESTION_SYNTHESIZE. VERIFY_CLAIM deps are added later by the QS
    # handlers via TaskResult.added_dep_edges.
    report.reads_notes = list(question_note_ids)
    report.depends_on = [
        DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR) for t_id in synth_task_ids
    ]
    spawned.append(report)

    titles_preview = " | ".join(sq.title[:50] for sq in out.sub_questions)
    return TaskResult(
        note_mutations=mutations,
        spawned_tasks=spawned,
        verdict=f"{len(out.sub_questions)} sub-question(s) — {titles_preview}",
    )


# --- ACH flow (sub-handler for QUESTION_SYNTHESIZE when pattern=ACH) --------


def _format_claim_digest(note: Note) -> str:
    claims = note.metadata.claims or []
    if not claims:
        return f"  (no claims extracted; snippet: {note.metadata.summary or note.description})"
    lines = []
    for c in claims:
        lines.append(f'  - "{c.text}" — quote: "{c.quote[:200]}"')
    return "\n".join(lines)


async def _run_ach_flow(
    ctx: HandlerContext,
    question: str,
    enriched: list[Note],
    synth_note_id: str,
) -> tuple[SynthesizerOutput, list[Note]]:
    """Three-phase ACH (ADR 0004).

    Phase 1: one LLM call generates 2-5 mutually-exclusive hypotheses.
    Phase 2: N parallel LLM calls, each evaluating one hypothesis
             against all M source digests.
    Phase 3: one HIGH-tier LLM call adjudicates using Heuer's rule
             (fewest inconsistencies wins).

    Returns (synth_out, hypothesis_notes). The synth_out reshapes the
    adjudication output into the SynthesizerOutput contract so the
    caller's synth_note construction doesn't branch. hypothesis_notes
    are the per-hypothesis notes with their verdict matrix row stored
    in HypothesisMetadata.
    """
    digest_parts = [
        f"Source {n.id} ({n.title}, tier {n.metadata.tier.value}):\n" f"{_format_claim_digest(n)}"
        for n in enriched
    ]
    evidence_digest = "\n\n".join(digest_parts)

    # Phase 1: hypothesis generation
    gen_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=AchHypothesisGenOutput,
        system_prompt=ACH_HYPOTHESIS_GEN_SYSTEM,
    )
    gen_user = (
        f"Question: {question}\n\nEvidence digest ({len(enriched)} sources):\n\n{evidence_digest}"
    )
    gen_r = await gen_agent.run(gen_user)
    hypotheses = gen_r.output.hypotheses
    logger.info("ach generated n=%d hypotheses", len(hypotheses))

    # Phase 2: per-hypothesis consistency (parallel)
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
            r = await cons_agent.run(user)
            return r.output.verdicts
        except Exception as exc:
            logger.warning("ach consistency failed hypothesis=%s err=%s", h.label, exc)
            return []

    matrix = await asyncio.gather(*(_evaluate(h) for h in hypotheses))

    # Phase 3: adjudication
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
    adj_r = await adj_agent.run(f"Question: {question}\n\nConsistency matrix:\n\n{matrix_text}")
    adj = adj_r.output
    logger.info("ach adopted=%r", adj.adopted_label)

    # Build hypothesis_notes with per-hypothesis verdict counts + stored
    # supporting/inconsistent/neutral source IDs.
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
                links=[Link(target_id=synth_note_id, edge_type="hypothesis_of_synthesis")],
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

    # Shape the adjudication into SynthesizerOutput for the caller.
    synth_out = SynthesizerOutput(
        bottom_line=adj.bottom_line,
        synthesis=adj.synthesis,
        disagreements=adj.disagreements,
        confidence_note=adj.confidence_note,
    )
    return synth_out, hypothesis_notes


# --- QUESTION_SYNTHESIZE ----------------------------------------------------


async def handle_question_synthesize(ctx: HandlerContext) -> TaskResult:
    question = ctx.task.goal

    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    brave = BraveClient(api_key=brave_key)
    brave_hits, academic_hits = await asyncio.gather(
        brave.search(question, count=5),
        search_academic(question, local=ctx.local, limit_per_source=3),
    )

    # Academic hits first so their richer metadata wins on URL dedup ties.
    combined: list = []
    seen_urls: set[str] = set()
    for h in [*academic_hits, *brave_hits]:
        if h.url and h.url not in seen_urls:
            combined.append(h)
            seen_urls.add(h.url)

    # Rerank by lexical snippet relevance before paying the fetch cost,
    # then cap at the top FETCH_LIMIT hits. Academic hits get a small
    # base bonus in score_hit() so they don't get outranked by
    # SEO-optimized Brave titles.
    FETCH_LIMIT = 8
    reranked = rerank(combined, question)
    hits = reranked[:FETCH_LIMIT]
    logger.info(
        "hits brave=%d academic=%d dedup=%d reranked_kept=%d question=%r",
        len(brave_hits),
        len(academic_hits),
        len(combined),
        len(hits),
        question[:60],
    )

    fetches = await asyncio.gather(*(fetch_and_extract(h.url) for h in hits))

    usable = [
        (hit, fetch)
        for hit, fetch in zip(hits, fetches, strict=True)
        if fetch is not None and fetch.markdown
    ]
    for hit, fetch in zip(hits, fetches, strict=True):
        if fetch is None or not fetch.markdown:
            logger.info("skip url=%s (fetch failed or no markdown)", hit.url)

    # Classify each usable source in parallel on the cheap_deterministic
    # LOW-tier model (ADR 0003). Routing is resolved once here rather than
    # per-call to keep the invariant check centralized; the tier classifier
    # is out of scope for cross-family so no forbidden_family is needed.
    tier_model_id = ctx.routing.model_id_for(RoleClass.CHEAP_DETERMINISTIC, TaskTier.LOW)
    tier_results = await asyncio.gather(
        *(
            classify_source(
                title=fetch.title or hit.title or hit.url,
                url=hit.url,
                snippet=hit.snippet,
                content=fetch.markdown,
                model_id=tier_model_id,
                local=ctx.local,
            )
            for hit, fetch in usable
        )
    )

    source_notes: list[Note] = []
    for (hit, fetch), (tier, rationale, confidence, peer_reviewed) in zip(
        usable, tier_results, strict=True
    ):
        title = fetch.title or hit.title or hit.url
        markdown = fetch.markdown
        # Size-first source routing (ADR 0007): long sources get a
        # StructuredContent view so the analyzer can see the shape of the
        # document without consuming its full content budget. The raw
        # markdown still lives on the note so a future tool call can pull
        # specific sections.
        structured = build_structured_content(title, markdown) if is_long_source(markdown) else None
        source_notes.append(
            Note(
                id=new_note_id("source"),
                type=NoteType.SOURCE,
                title=title,
                description=hit.snippet[:280],
                content=markdown[:40000],
                metadata=SourceNoteMetadata(
                    url=hit.url,
                    title=fetch.title or hit.title or "Untitled",
                    authors=list(hit.authors),
                    venue=hit.venue,
                    year=hit.year,
                    citation_count=hit.citation_count,
                    tier=tier,
                    tier_rationale=rationale,
                    classifier_confidence=confidence,
                    peer_reviewed=peer_reviewed,
                    summary=hit.snippet,
                    structured_content=structured,
                ),
                created_by=ctx.task.id,
                created_at=_now(),
                last_modified_at=_now(),
            )
        )

    if not source_notes:
        raise RuntimeError(
            f"no usable sources after fetching {len(hits)} candidates " f"for question={question!r}"
        )

    # Pick framings based on task.pattern:
    # - single_researcher: one neutral analyzer.
    # - multi_perspective: three complementary framings (neutral / skeptic /
    #   advocate), claims merged and tagged with perspective.
    # - debate: two adversarial framings (affirmative / negative), claims
    #   merged and judged by the JUDGE synthesizer prompt below.
    if ctx.task.pattern == OrchestrationPattern.MULTI_PERSPECTIVE:
        framings: tuple[Perspective, ...] = PERSPECTIVES
    elif ctx.task.pattern == OrchestrationPattern.DEBATE:
        framings = DEBATE_FRAMINGS
    else:
        framings = (Perspective(name="neutral", prompt_suffix=""),)

    def _build_analyzer(framing: Perspective) -> Agent:
        system = ANALYZER_SYSTEM
        if framing.prompt_suffix:
            system = ANALYZER_SYSTEM + "\n\nFraming for this pass:\n" + framing.prompt_suffix
        return Agent(
            make_model(ctx.model_id, ctx.local),
            output_type=AnalyzerOutput,
            system_prompt=system,
        )

    framing_agents: dict[str, Agent] = {p.name: _build_analyzer(p) for p in framings}

    def _analyzer_user_message(note: Note) -> str:
        # For long sources, send the StructuredContent outline + a
        # capped excerpt of the full body so the analyzer can still pull
        # verbatim quotes but doesn't have to scan 40K chars of raw
        # markdown. Short sources send the whole content inline.
        if note.metadata.structured_content is not None:
            outline = render_outline(note.metadata.structured_content)
            excerpt = note.content[:6000]
            body = (
                f"Structured outline (this source is long; the full "
                f"markdown follows the outline, truncated):\n\n{outline}"
                f"\n\n---\n\nRaw excerpt (first 6000 chars):\n{excerpt}"
            )
        else:
            body = f"Content:\n{note.content}"
        return (
            f"Question: {question}\n\n"
            f"Source: {note.title}\nURL: {note.metadata.url}\n\n"
            f"{body}"
        )

    async def _analyze_one(
        note: Note, framing_name: str
    ) -> tuple[Note, str, AnalyzerOutput | None]:
        user = _analyzer_user_message(note)
        agent = framing_agents[framing_name]
        try:
            r = await agent.run(user)
            return note, framing_name, r.output
        except Exception as exc:
            logger.warning("analyzer failed id=%s framing=%s err=%s", note.id, framing_name, exc)
            return note, framing_name, None

    pairs = [(n, f.name) for n in source_notes for f in framings]
    analyses = await asyncio.gather(*(_analyze_one(n, fname) for n, fname in pairs))

    # Group results by source_note. Each note ends with claims from all
    # framings interleaved; off_topic is AND-ed across framings (a source
    # is only dropped if EVERY framing says it's off-topic — any framing
    # finding something worth extracting keeps the source).
    analyzer_family = ctx.routing.family_of(ctx.model_id)
    by_note: dict[str, list[tuple[str, AnalyzerOutput | None]]] = {n.id: [] for n in source_notes}
    for note, fname, out in analyses:
        by_note[note.id].append((fname, out))

    enriched: list[Note] = []
    dropped_off_topic = 0
    for note in source_notes:
        framing_outs = by_note[note.id]
        non_null = [(f, o) for f, o in framing_outs if o is not None]
        if non_null and all(o.off_topic for _, o in non_null):
            # All framings agree the source is off-topic — drop it.
            dropped_off_topic += 1
            continue
        claims: list[ClaimItem] = []
        claim_idx = 0
        for fname, out in framing_outs:
            if out is None or out.off_topic:
                continue
            for c in out.claims:
                claims.append(
                    ClaimItem(
                        id=f"{note.id}-{claim_idx}",
                        text=c.text,
                        quote=c.quote,
                        extractor_confidence=c.extractor_confidence,
                        analyzed_by_family=analyzer_family,
                        perspective=fname,
                    )
                )
                claim_idx += 1
        new_meta = note.metadata.model_copy(update={"claims": claims})
        enriched.append(note.model_copy(update={"metadata": new_meta}))
    if dropped_off_topic:
        logger.info("dropped_off_topic n=%d question=%r", dropped_off_topic, question[:60])

    is_debate = ctx.task.pattern == OrchestrationPattern.DEBATE
    is_multi = ctx.task.pattern == OrchestrationPattern.MULTI_PERSPECTIVE
    is_ach = ctx.task.pattern == OrchestrationPattern.ACH

    synth_note_id = new_note_id("synthesis")
    ach_hypothesis_notes: list[Note] = []

    if is_ach:
        synth_out, ach_hypothesis_notes = await _run_ach_flow(
            ctx=ctx,
            question=question,
            enriched=enriched,
            synth_note_id=synth_note_id,
        )
    else:
        # Debate uses the judge prompt — same output shape as synth so
        # the downstream note / report plumbing is unchanged.
        synth_system = JUDGE_SYSTEM if is_debate else SYNTHESIZER_SYSTEM
        synth_agent = Agent(
            make_model(ctx.model_id, ctx.local),
            output_type=SynthesizerOutput,
            system_prompt=synth_system,
        )
        lines: list[str] = []
        # Debate claims are always tagged with perspective — the judge
        # needs to know which side adduced each quote.
        tag_perspectives = is_multi or is_debate
        for n in enriched:
            if not n.metadata.claims:
                continue
            lines.append(f"Source: {n.title} ({n.metadata.url})")
            for c in n.metadata.claims:
                # Under multi_perspective / debate, tag each claim with
                # its framing so the synthesizer (or judge) can see where
                # framings agree / diverge on the same source. Under
                # single_researcher every claim is "neutral"; tagging is
                # noise — omit.
                prefix = f"[{c.perspective}] " if tag_perspectives else ""
                lines.append(f"  - {prefix}Claim: {c.text}")
                lines.append(f'    Quote: "{c.quote}"')
            lines.append("")
        if not lines:
            # No claims extracted; fall back to raw snippets so the
            # synthesizer has something.
            for n in enriched:
                lines.append(f"Source: {n.title} ({n.metadata.url})")
                lines.append(f"  Snippet: {n.metadata.summary or n.description}")
                lines.append("")
        synth_user = f"Question: {question}\n\n" + "\n".join(lines)
        synth_r = await synth_agent.run(synth_user)
        synth_out = synth_r.output

    synth_note = Note(
        id=synth_note_id,
        type=NoteType.SYNTHESIS,
        title=f"Synthesis: {question[:80]}",
        description=synth_out.bottom_line,
        content=synth_out.synthesis,
        links=[Link(target_id=n.id, edge_type="source_for_synthesis") for n in enriched]
        + [Link(target_id=h.id, edge_type="hypothesis_of_synthesis") for h in ach_hypothesis_notes],
        metadata=SynthesisMetadata(
            pattern=(ctx.task.pattern or OrchestrationPattern.SINGLE_RESEARCHER).value,
            surviving_dissent=synth_out.disagreements,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    q_note = ctx.notes.get(ctx.task.reads_notes[0])
    q_new_meta = q_note.metadata.model_copy(
        update={
            "status": "SYNTHESIZED",
            "adopted_position": synth_out.bottom_line,
        }
    )
    q_updated = q_note.model_copy(update={"metadata": q_new_meta})

    mutations = [NoteMutation(kind="create", note=n) for n in enriched]
    for h in ach_hypothesis_notes:
        mutations.append(NoteMutation(kind="create", note=h))
    mutations.append(NoteMutation(kind="create", note=synth_note))
    mutations.append(NoteMutation(kind="replace", note=q_updated))

    # --- maker_checker: spawn VERIFY_CLAIM tasks for top claims ---------
    verify_tasks: list = []
    added_deps: list[DepEdgeAdd] = []
    wr_task_id = ctx.task.input_refs.get("write_report_task_id")
    picked = select_claims_to_verify(enriched)
    for note, claim in picked:
        v_task = emit_verify_claim(
            claim=claim,
            source_note=note,
            question=question,
            write_report_task_id=wr_task_id,
            parent_task_id=ctx.task.id,
        )
        verify_tasks.append(v_task)
        if wr_task_id:
            added_deps.append(
                DepEdgeAdd(
                    downstream=wr_task_id,
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


# --- VERIFY_CLAIM -----------------------------------------------------------


async def handle_verify_claim(ctx: HandlerContext) -> TaskResult:
    """Cross-family verification of one claim (ADR 0008).

    Fetches independent sources with a re-phrased query, runs the
    judgment-role verifier (different model family than the analyzer
    by executor construction), and emits a verdict. Updates the
    source_note's ClaimItem.verification_status in place + writes a
    decision_note with the verifier's rationale.
    """
    claim_id = ctx.task.input_refs.get("claim_id")
    source_note_id = ctx.task.input_refs.get("source_note_id")
    question = ctx.task.input_refs.get("question", "")
    if not claim_id or not source_note_id:
        raise RuntimeError(
            "VERIFY_CLAIM requires input_refs['claim_id'] and input_refs['source_note_id']"
        )

    source_note = ctx.notes.get(source_note_id)
    claim = next(
        (c for c in getattr(source_note.metadata, "claims", []) if c.id == claim_id),
        None,
    )
    if claim is None:
        raise RuntimeError(f"claim {claim_id!r} not found on source_note {source_note_id!r}")

    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    # Re-phrase: the verifier should search for independent corroboration /
    # refutation. Using the claim text as the query tends to surface the
    # same primary source, so we prepend a falsification cue.
    search_query = f'evidence about: "{claim.text}"'
    brave = BraveClient(api_key=brave_key)
    hits = await brave.search(search_query, count=5)
    primary_url = getattr(source_note.metadata, "url", None)
    independent_hits = [h for h in hits if h.url != primary_url][:3]
    logger.info(
        "verify_claim claim_id=%s independent_hits=%d primary=%s",
        claim_id,
        len(independent_hits),
        primary_url,
    )

    # Fetch in parallel; on any failure we fall back to the Brave snippet.
    fetches = await asyncio.gather(
        *(fetch_and_extract(h.url) for h in independent_hits), return_exceptions=True
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
        r = await verifier.run(user_prompt)
        vout = r.output
        verdict_label = vout.verdict
        rationale_text = vout.rationale
        disagreements = vout.disagreement_notes

    # Write the verification as a decision_note so it shows up in the note
    # graph + UI. Linked back to the source_note being checked.
    v_note_id = new_note_id("verification")
    body_parts = [
        f"**Verdict:** {verdict_label}",
        "",
        rationale_text,
    ]
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
        links=[Link(target_id=source_note_id, edge_type="verification_of")],
        metadata=DecisionMetadata(
            category="verification",
            rationale=f"cross-family verification by {verifier_family}",
            relates_to_task=ctx.task.id,
        ),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    # Update the ClaimItem in place on the source_note.
    status_map = {
        "SUPPORTS": VerificationStatus.SUPPORTS,
        "REFUTES": VerificationStatus.REFUTES,
        "INCONCLUSIVE": VerificationStatus.INCONCLUSIVE,
    }
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
        for c in (source_note.metadata.claims or [])
    ]
    new_src_meta = source_note.metadata.model_copy(update={"claims": updated_claims})
    src_updated = source_note.model_copy(update={"metadata": new_src_meta})

    return TaskResult(
        note_mutations=[
            NoteMutation(kind="create", note=verification_note),
            NoteMutation(kind="replace", note=src_updated),
        ],
        verdict=f"{verdict_label}: {rationale_text[:100]}",
    )


# --- WRITE_REPORT -----------------------------------------------------------


async def handle_write_report(ctx: HandlerContext) -> TaskResult:
    q_notes = [n for n in ctx.notes.all() if n.type == NoteType.QUESTION]
    synth_notes = [n for n in ctx.notes.all() if n.type == NoteType.SYNTHESIS]
    source_notes = [n for n in ctx.notes.all() if n.type == NoteType.SOURCE]
    verification_notes = [
        n
        for n in ctx.notes.all()
        if n.type == NoteType.DECISION and n.metadata.category == "verification"
    ]

    # Aggregate verification counts for the report intro.
    verdict_counts = {"SUPPORTS": 0, "REFUTES": 0, "INCONCLUSIVE": 0, "UNVERIFIED": 0}
    for sn in source_notes:
        for c in sn.metadata.claims:
            verdict_counts[c.verification_status.value] = (
                verdict_counts.get(c.verification_status.value, 0) + 1
            )

    parts: list[str] = ["# RESEARCH NOTES (context for the report)"]
    if sum(v for k, v in verdict_counts.items() if k != "UNVERIFIED") > 0:
        parts.append(
            f"\n## Verification summary\n"
            f"Cross-family verification results across all extracted claims: "
            f"SUPPORTS={verdict_counts.get('SUPPORTS', 0)}, "
            f"REFUTES={verdict_counts.get('REFUTES', 0)}, "
            f"INCONCLUSIVE={verdict_counts.get('INCONCLUSIVE', 0)}, "
            f"UNVERIFIED={verdict_counts.get('UNVERIFIED', 0)}."
        )
    for q in q_notes:
        parts.append(f"\n## Question\n{q.title}")
        parts.append(f"Adopted position: {q.metadata.adopted_position or '(none)'}")
    for s in synth_notes:
        parts.append(f"\n## Synthesis: {s.title}")
        parts.append(f"Bottom line: {s.description}")
        parts.append(f"Body:\n{s.content}")
        if s.metadata.surviving_dissent:
            parts.append("Disagreements:")
            for d in s.metadata.surviving_dissent:
                parts.append(f"  - {d}")
    parts.append("\n## Sources")
    for sn in source_notes:
        parts.append(f"- {sn.title} — {sn.metadata.url}  (Tier {sn.metadata.tier.value})")
        for c in sn.metadata.claims:
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

    report_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=ReportOutput,
        system_prompt=REPORT_SYSTEM,
    )
    r = await report_agent.run("\n".join(parts))

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

    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=report_note)],
        verdict=f"report emitted as note {report_note.id}",
    )


# --- Registration -----------------------------------------------------------


def register_handlers(executor: AgentExecutor) -> None:
    """Register the current handler set on an AgentExecutor."""
    executor.register(TaskType.LANDSCAPE_SURVEY, handle_landscape_survey)
    executor.register(TaskType.DECOMPOSE, handle_decompose)
    executor.register(TaskType.QUESTION_SYNTHESIZE, handle_question_synthesize)
    executor.register(TaskType.VERIFY_CLAIM, handle_verify_claim)
    executor.register(TaskType.WRITE_REPORT, handle_write_report)


# Backwards-compatible alias — older call sites used the v0 name.
register_v0_handlers = register_handlers
