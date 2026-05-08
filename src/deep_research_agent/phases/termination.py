"""Phase 4: termination gate chain.

Sits between all sub-question synthesis and WRITE_REPORT:

    QS* (+ VERIFY_CLAIM) → CHECK_TERMINATION_READY → VALIDATE_COMPLETION → WRITE_REPORT

CHECK_TERMINATION_READY (deterministic, no LLM)
  Structural audit per ADR 0009:
    - No non-terminal tasks remain.
    - Every question_note has status SYNTHESIZED.
    - Every contested sub-question has at least one disconfirmation
      pass (multi_perspective / debate / ach / ADVERSARIAL_CRITIQUE)
      visible in the task graph.

VALIDATE_COMPLETION (LLM, HIGH-tier judgment)
  Six-gate audit (per TDD §5.12):
    1. Bottom line is grounded in cited evidence.
    2. Disagreements across sources are surfaced, not averaged.
    3. No phantom citations — every cited source exists and carries
       the claim the synthesis attributes to it.
    4. Contested questions actually probed (disconfirmation evidence
       shows up in the synthesis, not just in the graph).
    5. Scope discipline — synthesis answers the query, not a
       broadened version of it.
    6. Triangulation — load-bearing claims have multi-source support.

Both gates emit decision_notes with their verdict. On fail, current
MVP logs and passes through; a follow-up polish pass adds remediation
loops and ESCALATED status transitions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..scheduler.ids import new_task_id
from ..schemas import DepEdge, DepScope, Task, TaskID
from ..schemas.enums import (
    DependencyType,
    RoleClass,
    TaskTier,
    TaskType,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def emit_check_termination_ready(
    parent_task_id: TaskID,
    upstream_synth_task_ids: list[TaskID],
) -> Task:
    """CHECK_TERMINATION_READY task. Deterministic — cheap_deterministic role.

    Depends on every QUESTION_SYNTHESIZE task so the structural audit
    only runs after all syntheses have landed. VERIFY_CLAIM tasks get
    grafted onto this same task by the QS handler so verifications also
    complete before the audit fires.
    """
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="audit termination readiness",
        type=TaskType.CHECK_TERMINATION_READY,
        role=RoleClass.CHEAP_DETERMINISTIC,
        tier=TaskTier.LOW,
        depends_on=[
            DepEdge(upstream=t_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)
            for t_id in upstream_synth_task_ids
        ],
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria=(
            "structural audit: no pending work, every sub-question synthesized, "
            "contested questions have disconfirmation passes"
        ),
        created_at=_now(),
    )


def emit_validate_completion(
    parent_task_id: TaskID,
    check_task_id: TaskID,
    question_note_ids: list[str],
) -> Task:
    """VALIDATE_COMPLETION task. HIGH-tier judgment (LLM audit)."""
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal="validate completion (six-gate audit)",
        type=TaskType.VALIDATE_COMPLETION,
        role=RoleClass.JUDGMENT,
        tier=TaskTier.HIGH,
        reads_notes=list(question_note_ids),
        depends_on=[DepEdge(upstream=check_task_id, kind=DependencyType.PRODUCES_CONTEXT_FOR)],
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria=(
            "six-gate audit: evidence-grounding, disagreement surfacing, "
            "no phantom citations, contested probing, scope discipline, "
            "triangulation"
        ),
        created_at=_now(),
    )
