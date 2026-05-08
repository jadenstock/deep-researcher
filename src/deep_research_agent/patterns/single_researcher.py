"""single_researcher pattern — task-emission helpers.

In v0 the pattern is executed by a single fat `QUESTION_SYNTHESIZE`
handler that runs search → fetch → analyze → synthesize imperatively.
This module provides the helpers that emit the top-level tasks for one
sub-question: one QUESTION_SYNTHESIZE + one WRITE_REPORT downstream.

Later milestones (v2+) split the imperative flow into explicit
SEARCH, FETCH_AND_EXTRACT, ANALYZE_SOURCE sub-tasks so the replanner
can see and mutate the sub-DAG.
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


def emit_decompose(
    query: str,
    landscape_note_id: NoteID,
    parent_task_id: TaskID,
) -> Task:
    """Emit a DECOMPOSE task that reads the landscape note for evidence-grounded
    classification (TDD §5.2)."""
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


def emit_question_synthesize(
    question: str,
    question_note_id: NoteID,
    parent_task_id: TaskID,
) -> Task:
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=question,
        type=TaskType.QUESTION_SYNTHESIZE,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        pattern=OrchestrationPattern.SINGLE_RESEARCHER,
        question_round=QuestionRound.STRUCTURAL,
        reads_notes=[question_note_id],
        depends_on=[DepEdge(upstream=parent_task_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)],
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria="emit a synthesis_note answering the question",
        created_at=_now(),
    )


def emit_write_report(
    question_note_id: NoteID,
    upstream_synth_task_id: TaskID,
    parent_task_id: TaskID,
) -> Task:
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="write the final research report",
        type=TaskType.WRITE_REPORT,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        reads_notes=[question_note_id],
        depends_on=[
            DepEdge(upstream=upstream_synth_task_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
        ],
        success_criteria="emit a final markdown report",
        created_at=_now(),
    )
