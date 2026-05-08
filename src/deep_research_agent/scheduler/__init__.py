"""Deterministic scheduler, task graph, and note graph.

No LLM lives here. The scheduler owns state transitions; executors own
agent-layer computation and return note-mutation requests + spawned
tasks via TaskResult.
"""

from .ids import new_note_id, new_run_id, new_task_id
from .note_graph import NoteGraph, NoteVersionConflict
from .scheduler import (
    DepEdgeAdd,
    Executor,
    NoteMutation,
    NoteReader,
    Scheduler,
    SchedulerDeadlock,
    TaskResult,
)
from .task_graph import TaskGraph

__all__ = [
    "DepEdgeAdd",
    "Executor",
    "NoteGraph",
    "NoteMutation",
    "NoteReader",
    "NoteVersionConflict",
    "Scheduler",
    "SchedulerDeadlock",
    "TaskGraph",
    "TaskResult",
    "new_note_id",
    "new_run_id",
    "new_task_id",
]
