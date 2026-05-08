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
from ..patterns.single_researcher import (
    emit_decompose,
    emit_question_synthesize,
    emit_write_report,
)
from ..retrieval import BraveClient, fetch_and_extract
from ..scheduler import NoteMutation, TaskResult
from ..scheduler.ids import new_note_id
from ..schemas import (
    ClaimItem,
    DecisionMetadata,
    LandscapeMetadata,
    Link,
    Note,
    PositionItem,
    QuestionMetadata,
    SourceNoteMetadata,
    SynthesisMetadata,
    ThemeItem,
)
from ..schemas.enums import NoteType, QuestionClassification, TaskType
from ..tiering.simple import quick_tier
from .executor import AgentExecutor, HandlerContext
from .outputs import AnalyzerOutput, LandscapeOutput, ReportOutput, SynthesizerOutput
from .prompts import (
    ANALYZER_SYSTEM,
    LANDSCAPE_SYSTEM,
    REPORT_SYSTEM,
    SYNTHESIZER_SYSTEM,
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


async def handle_decompose(ctx: HandlerContext) -> TaskResult:
    """v1.1: still trivial (one question, no LLM decomposition). v1.2 uses
    the landscape_note for evidence-grounded decomposition."""
    query = ctx.task.goal
    q_note_id = new_note_id("question")
    q_note = Note(
        id=q_note_id,
        type=NoteType.QUESTION,
        title=query,
        description="Primary research question (v0 single-question pipeline).",
        content=query,
        metadata=QuestionMetadata(classification=QuestionClassification.SYNTHESIS),
        created_by=ctx.task.id,
        created_at=_now(),
        last_modified_at=_now(),
    )
    q_synth = emit_question_synthesize(query, q_note_id, ctx.task.id)
    report = emit_write_report(q_note_id, q_synth.id, ctx.task.id)
    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=q_note)],
        spawned_tasks=[q_synth, report],
        verdict=f"decomposed as single question {q_note_id}",
    )


# --- QUESTION_SYNTHESIZE ----------------------------------------------------


async def handle_question_synthesize(ctx: HandlerContext) -> TaskResult:
    question = ctx.task.goal

    brave_key = ctx.local.retrieval.brave_api_key
    if not brave_key:
        raise RuntimeError("no brave_api_key configured in local.toml")

    brave = BraveClient(api_key=brave_key)
    hits = await brave.search(question, count=5)
    logger.info("brave hits=%d question=%r", len(hits), question[:60])

    fetches = await asyncio.gather(*(fetch_and_extract(h.url) for h in hits))

    source_notes: list[Note] = []
    for hit, fetch in zip(hits, fetches, strict=True):
        if fetch is None or not fetch.markdown:
            logger.info("skip url=%s (fetch failed or no markdown)", hit.url)
            continue
        tier, rationale = quick_tier(hit.url)
        source_notes.append(
            Note(
                id=new_note_id("source"),
                type=NoteType.SOURCE,
                title=fetch.title or hit.title or hit.url,
                description=hit.snippet[:280],
                content=fetch.markdown[:20000],
                metadata=SourceNoteMetadata(
                    url=hit.url,
                    title=fetch.title or hit.title or "Untitled",
                    tier=tier,
                    tier_rationale=rationale,
                    classifier_confidence=0.5,
                    peer_reviewed=False,
                    summary=hit.snippet,
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

    analyzer = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=AnalyzerOutput,
        system_prompt=ANALYZER_SYSTEM,
    )

    async def _analyze(note: Note) -> AnalyzerOutput | None:
        user = (
            f"Question: {question}\n\n"
            f"Source: {note.title}\nURL: {note.metadata.url}\n\n"
            f"Content:\n{note.content}"
        )
        try:
            r = await analyzer.run(user)
            return r.output
        except Exception as exc:
            logger.warning("analyzer failed id=%s err=%s", note.id, exc)
            return None

    analyses = await asyncio.gather(*(_analyze(n) for n in source_notes))

    enriched: list[Note] = []
    for note, out in zip(source_notes, analyses, strict=True):
        if out is None or out.off_topic:
            enriched.append(note)
            continue
        claims = [
            ClaimItem(
                id=f"{note.id}-{i}",
                text=c.text,
                quote=c.quote,
                extractor_confidence=c.extractor_confidence,
            )
            for i, c in enumerate(out.claims)
        ]
        new_meta = note.metadata.model_copy(update={"claims": claims})
        enriched.append(note.model_copy(update={"metadata": new_meta}))

    synth_agent = Agent(
        make_model(ctx.model_id, ctx.local),
        output_type=SynthesizerOutput,
        system_prompt=SYNTHESIZER_SYSTEM,
    )
    lines: list[str] = []
    for n in enriched:
        if not n.metadata.claims:
            continue
        lines.append(f"Source: {n.title} ({n.metadata.url})")
        for c in n.metadata.claims:
            lines.append(f"  - Claim: {c.text}")
            lines.append(f'    Quote: "{c.quote}"')
        lines.append("")
    if not lines:
        # No claims extracted; fall back to raw snippets so the synthesizer has something.
        for n in enriched:
            lines.append(f"Source: {n.title} ({n.metadata.url})")
            lines.append(f"  Snippet: {n.metadata.summary or n.description}")
            lines.append("")

    synth_user = f"Question: {question}\n\n" + "\n".join(lines)
    synth_r = await synth_agent.run(synth_user)
    synth_out = synth_r.output

    synth_note_id = new_note_id("synthesis")
    synth_note = Note(
        id=synth_note_id,
        type=NoteType.SYNTHESIS,
        title=f"Synthesis: {question[:80]}",
        description=synth_out.bottom_line,
        content=synth_out.synthesis,
        links=[Link(target_id=n.id, edge_type="source_for_synthesis") for n in enriched],
        metadata=SynthesisMetadata(
            pattern="single_researcher",
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
    mutations.append(NoteMutation(kind="create", note=synth_note))
    mutations.append(NoteMutation(kind="replace", note=q_updated))

    return TaskResult(
        note_mutations=mutations,
        verdict=f"synthesized {len(enriched)} sources → {synth_note_id}",
    )


# --- WRITE_REPORT -----------------------------------------------------------


async def handle_write_report(ctx: HandlerContext) -> TaskResult:
    q_notes = [n for n in ctx.notes.all() if n.type == NoteType.QUESTION]
    synth_notes = [n for n in ctx.notes.all() if n.type == NoteType.SYNTHESIS]
    source_notes = [n for n in ctx.notes.all() if n.type == NoteType.SOURCE]

    parts: list[str] = ["# RESEARCH NOTES (context for the report)"]
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
            parts.append(f'    - "{c.quote[:180]}" → {c.text}')

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
    executor.register(TaskType.WRITE_REPORT, handle_write_report)


# Backwards-compatible alias — older call sites used the v0 name.
register_v0_handlers = register_handlers
