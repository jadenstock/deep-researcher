"""Task-emission helpers for the streaming pipeline.

Module name is historical; this is now the full emission surface for
the pipeline rather than a pattern-specific helper set. The old fused
`single_researcher` path was a pre-corpus relic; it's gone. All
orchestration patterns (single_researcher / multi_perspective / debate /
ach) run on the same scout → fetch → analyze → synthesize skeleton and
differ only in the set of framings passed to ANALYZE_SOURCE and the
synthesizer prompt.

Streaming pipeline task types:

- SCOUT_SOURCES         — broad link discovery; adds SCOUTED source_notes.
- FETCH_AND_EXTRACT     — promotes one SCOUTED source to FETCHED (fetch +
                          tier-classify).
- ANALYZE_SOURCE        — extracts claims from one FETCHED source in
                          service of one question; promotes to ANALYZED.
- REPLAN (RESCORE)      — replanner cycle — here called from emit_rescore.
- QUESTION_SYNTHESIZE   — readiness-gated synthesis; re-emits itself
                          while more analysis is in flight.
- VERIFY_CLAIM          — post-synthesis independent check on cited claims.

All retrieval-phase tasks (SCOUT / FETCH / ANALYZE / RESCORE) set
`retrieval_ignores=True` so they dispatch regardless of upstream
dependencies — the scheduler already honors this (ADR 0006).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..scheduler.ids import new_task_id
from ..schemas import DepEdge, DepScope, Task, TaskID
from ..schemas.enums import (
    DependencyType,
    OrchestrationPattern,
    QuestionRound,
    RoleClass,
    TaskTier,
    TaskType,
)
from ..schemas.ids import NoteID


def _now() -> datetime:
    return datetime.now(UTC)


# --- Core emitters (shared across patterns) --------------------------------


def emit_decompose(
    query: str,
    landscape_note_id: NoteID,
    parent_task_id: TaskID,
) -> Task:
    """DECOMPOSE reads the landscape_note to classify sub-questions."""
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=query,
        type=TaskType.DECOMPOSE,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        question_round=QuestionRound.STRUCTURAL,
        reads_notes=[landscape_note_id],
        depends_on=[DepEdge(upstream=parent_task_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)],
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria="emit question_notes + spawn research tasks",
        created_at=_now(),
    )


def emit_scout_sources(
    goal: str,
    scout_mode: str,
    parent_task_id: TaskID,
    question_note_ids: list[NoteID] | None = None,
) -> Task:
    """SCOUT_SOURCES task — run a bundle of reformulated queries and add
    SCOUTED source_notes to the corpus.

    `scout_mode` picks the reformulation bundle:
      - "landscape_seed": broad topical coverage (direct + contrarian +
        time_bounded + venue).
      - "question": per-question bundle (direct + evidence + review).
      - "verify_seed": broaden search around a specific claim during
        VERIFY_CLAIM (less breadth, higher recall).

    `question_note_ids` is stamped into the scouted source_notes so the
    RESCORE_RELEVANCE pass knows which questions to score against first.
    Empty list means "all open questions at scoring time" (useful for
    landscape seed).
    """
    input_refs: dict[str, str] = {"scout_mode": scout_mode}
    if question_note_ids:
        input_refs["question_note_ids"] = ",".join(question_note_ids)
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=goal,
        type=TaskType.SCOUT_SOURCES,
        role=RoleClass.CHEAP_DETERMINISTIC,
        tier=TaskTier.LOW,
        input_refs=input_refs,
        dep_scope=DepScope(retrieval_ignores=True, synthesis_waits=False),
        success_criteria="add SCOUTED source_notes + spawn rescore / fetch",
        created_at=_now(),
    )


def emit_fetch_and_extract(
    source_note_id: NoteID,
    parent_task_id: TaskID,
) -> Task:
    """FETCH_AND_EXTRACT — promote one SCOUTED source to FETCHED."""
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=f"fetch source {source_note_id}",
        type=TaskType.FETCH_AND_EXTRACT,
        role=RoleClass.CHEAP_DETERMINISTIC,
        tier=TaskTier.LOW,
        reads_notes=[source_note_id],
        input_refs={"source_note_id": source_note_id},
        dep_scope=DepScope(retrieval_ignores=True, synthesis_waits=False),
        success_criteria="update source_note with full content + tier classification",
        created_at=_now(),
    )


def emit_analyze_source(
    source_note_id: NoteID,
    question_note_id: NoteID,
    parent_task_id: TaskID,
    pattern: OrchestrationPattern = OrchestrationPattern.SINGLE_RESEARCHER,
) -> Task:
    """ANALYZE_SOURCE — extract claims from one source for one question.

    Pattern determines the framings the analyzer runs (single: neutral
    only; multi_perspective: three framings; debate: two adversarial).
    Claims are tagged with the question_id so the synthesizer can pull
    only the claims extracted for it.
    """
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=f"analyze source {source_note_id} for question {question_note_id}",
        type=TaskType.ANALYZE_SOURCE,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.MID,
        pattern=pattern,
        reads_notes=[source_note_id, question_note_id],
        input_refs={
            "source_note_id": source_note_id,
            "question_note_id": question_note_id,
        },
        dep_scope=DepScope(retrieval_ignores=True, synthesis_waits=False),
        success_criteria="extract claims tagged with question_note_id",
        created_at=_now(),
    )


def emit_rescore_relevance(
    source_note_ids: list[NoteID],
    parent_task_id: TaskID,
) -> Task:
    """RESCORE_RELEVANCE — batch-score SCOUTED sources against all open
    questions. Spawned lazily whenever a batch of new scouted sources
    lands; a single rescore pass covers N new sources x M open questions.
    """
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="rescore relevance of scouted sources",
        type=TaskType.RESCORE_RELEVANCE,
        role=RoleClass.CHEAP_DETERMINISTIC,
        tier=TaskTier.LOW,
        input_refs={
            "source_note_ids": ",".join(source_note_ids),
        },
        dep_scope=DepScope(retrieval_ignores=True, synthesis_waits=False),
        success_criteria="populate relevance on each source_note",
        created_at=_now(),
    )


def emit_question_synthesize(
    question: str,
    question_note_id: NoteID,
    parent_task_id: TaskID,
    termination_task_id: TaskID | None = None,
    pattern: OrchestrationPattern = OrchestrationPattern.SINGLE_RESEARCHER,
    poll_count: int = 0,
    depends_on: list[DepEdge] | None = None,
) -> Task:
    """QUESTION_SYNTHESIZE — readiness-gated synthesis.

    `termination_task_id` is threaded through so the handler can graft
    VERIFY_CLAIM sub-tasks it spawns onto the termination chain.
    `poll_count` tracks re-emissions under the readiness gate; the
    handler increments and caps it to bound re-dispatch.
    `depends_on` lets the handler re-emit with fresh dependencies on
    currently-pending retrieval/analysis tasks, so the next attempt
    only wakes after that batch drains.
    """
    input_refs: dict[str, str] = {"poll_count": str(poll_count)}
    if termination_task_id is not None:
        input_refs["termination_task_id"] = termination_task_id
    if depends_on is None:
        depends_on = [DepEdge(upstream=parent_task_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)]
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=question,
        type=TaskType.QUESTION_SYNTHESIZE,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        pattern=pattern,
        question_round=QuestionRound.STRUCTURAL,
        reads_notes=[question_note_id],
        input_refs=input_refs,
        depends_on=depends_on,
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria="emit a synthesis_note answering the question",
        created_at=_now(),
    )


def emit_meta_synthesize(
    question_note_ids: list[NoteID],
    upstream_synth_task_ids: list[TaskID],
    parent_task_id: TaskID,
) -> Task:
    """META_SYNTHESIZE — a single cross-question reconciliation pass.

    Runs after every per-question synthesis completes. Reads all
    synthesis_notes and produces one cross-question synthesis_note
    that identifies tensions, bridges, dependencies, and the overall
    research bottom line. Feeds WRITE_REPORT.

    Depends on every QS task so it only dispatches once individual
    syntheses have landed.
    """
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="cross-question synthesis",
        type=TaskType.META_SYNTHESIZE,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        reads_notes=list(question_note_ids),
        depends_on=[
            DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
            for t_id in upstream_synth_task_ids
        ],
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria=("emit one synthesis_note reconciling all per-question findings"),
        created_at=_now(),
    )


def emit_write_report(
    question_note_ids: list[NoteID],
    upstream_synth_task_ids: list[TaskID],
    parent_task_id: TaskID,
) -> Task:
    """Emit a WRITE_REPORT task with deps on every sub-question's synthesis."""
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="write the final research report",
        type=TaskType.WRITE_REPORT,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        reads_notes=list(question_note_ids),
        depends_on=[
            DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
            for t_id in upstream_synth_task_ids
        ],
        success_criteria="emit a final markdown report",
        created_at=_now(),
    )
