"""Task model (TDD §4.1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import (
    DependencyType,
    OrchestrationPattern,
    QuestionRound,
    RoleClass,
    TaskStatus,
    TaskTier,
    TaskType,
)
from .ids import NoteID, TaskID


class DepEdge(BaseModel):
    """Typed dependency from one task to another."""

    upstream: TaskID
    kind: DependencyType


class DepScope(BaseModel):
    """Per-task-type attribute controlling when dependencies block.

    Retrieval-phase tasks run regardless of upstream synthesis deps.
    Synthesis-phase tasks wait in BLOCKED_ON_SYNTHESIS_DEP until upstream
    synthesis is DONE.
    """

    retrieval_ignores: bool = False
    synthesis_waits: bool = True


class Task(BaseModel):
    id: TaskID
    parent_id: TaskID | None = None
    goal: str
    type: TaskType
    role: RoleClass
    tier: TaskTier
    pattern: OrchestrationPattern | None = None
    question_round: QuestionRound | None = None
    status: TaskStatus = TaskStatus.PENDING
    success_criteria: str
    depends_on: list[DepEdge] = Field(default_factory=list)
    dep_scope: DepScope = Field(default_factory=DepScope)
    reads_notes: list[NoteID] = Field(default_factory=list)
    writes_notes: list[NoteID] = Field(default_factory=list)
    spawned_sub_tasks: list[TaskID] = Field(default_factory=list)
    # Free-form string refs threaded between handlers. Used for pass-through
    # identifiers that don't belong in `goal` or `reads_notes` — e.g.
    # VERIFY_CLAIM carries claim_id, source_note_id, and the downstream
    # WRITE_REPORT task_id so verification deps can be wired in.
    input_refs: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None
