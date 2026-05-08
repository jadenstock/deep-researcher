"""Scheduler — the deterministic dispatch loop.

v0: serial dispatch of ready tasks. Parallel dispatch via asyncio.gather
is a later optimization (v1 when sub-question retrieval fans out).

The scheduler is the only writer to the note graph. Executors return a
TaskResult describing what they want to write + spawn; the scheduler
applies those under its write lock, updates status, and loops.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..schemas import Note, NoteID, NoteType, Task, TaskStatus
from .note_graph import NoteGraph
from .task_graph import TaskGraph

logger = logging.getLogger(__name__)

TaskCallback = Callable[[Task], None]
TaskDoneCallback = Callable[[Task, "TaskResult"], None]
NoteMutationCallback = Callable[["NoteMutation", Task], None]


# --- Read-only note view handed to executors --------------------------------


@runtime_checkable
class NoteReader(Protocol):
    """Read-only view of the note graph passed to executors.

    Executors MUST NOT mutate the note graph directly. Mutations travel
    back to the scheduler via TaskResult.note_mutations and are applied
    under the scheduler's write lock.
    """

    def get(self, note_id: NoteID) -> Note: ...
    def by_type(self, note_type: NoteType) -> list[Note]: ...
    def all(self) -> Iterable[Note]: ...
    def __contains__(self, note_id: object) -> bool: ...


# --- Executor contract ------------------------------------------------------


class NoteMutation(BaseModel):
    """A request to create or replace a note. Applied by the scheduler."""

    kind: Literal["create", "replace"]
    note: Note


class TaskResult(BaseModel):
    """What an executor returns for one completed task."""

    note_mutations: list[NoteMutation] = Field(default_factory=list)
    spawned_tasks: list[Task] = Field(default_factory=list)
    verdict: str = ""


@runtime_checkable
class Executor(Protocol):
    """Runs one task and returns its result. No side effects on graph state."""

    async def execute(self, task: Task, notes: NoteReader) -> TaskResult: ...


# --- Scheduler --------------------------------------------------------------


class SchedulerDeadlock(RuntimeError):
    """Raised when there are no ready tasks but not all tasks are terminal.

    Typically means a dependency points at a task that was abandoned
    without cascading, or a dep edge references a task that no longer exists.
    """


class Scheduler:
    def __init__(
        self,
        task_graph: TaskGraph,
        note_graph: NoteGraph,
        executor: Executor,
        on_task_start: TaskCallback | None = None,
        on_task_done: TaskDoneCallback | None = None,
        on_note_mutation: NoteMutationCallback | None = None,
    ) -> None:
        self.task_graph = task_graph
        self.note_graph = note_graph
        self.executor = executor
        self._write_lock = asyncio.Lock()
        self._on_task_start = on_task_start
        self._on_task_done = on_task_done
        self._on_note_mutation = on_note_mutation

    async def run(self) -> None:
        """Dispatch ready tasks until every task is terminal.

        All tasks ready in the same tick run concurrently via
        asyncio.gather. Note-graph writes stay serialized behind the
        scheduler's write lock; task-graph mutations happen under the
        same lock (via _apply_result).
        """
        while not self.task_graph.all_terminal():
            ready = self.task_graph.get_ready()
            if not ready:
                blocked = [
                    (t.id, t.status.value, [(e.upstream, e.kind.value) for e in t.depends_on])
                    for t in self.task_graph.all()
                    if t.status == TaskStatus.PENDING
                ]
                raise SchedulerDeadlock(
                    f"No ready tasks and {len(blocked)} still PENDING. "
                    f"Blocked tasks and their dep edges: {blocked}"
                )
            await asyncio.gather(*(self._run_one(t) for t in ready))

    async def _run_one(self, task: Task) -> None:
        self.task_graph.update_status(task.id, TaskStatus.RUNNING)
        logger.info("dispatch task_id=%s type=%s", task.id, task.type.value)
        if self._on_task_start is not None:
            self._on_task_start(task)
        try:
            result = await self.executor.execute(task, self.note_graph)
        except Exception:
            self.task_graph.update_status(task.id, TaskStatus.ABANDONED)
            logger.exception("task_id=%s abandoned due to exception", task.id)
            raise
        async with self._write_lock:
            self._apply_result(task, result)
        self._finish(task)
        if self._on_task_done is not None:
            self._on_task_done(task, result)

    def _apply_result(self, task: Task, result: TaskResult) -> None:
        for mut in result.note_mutations:
            if mut.kind == "create":
                self.note_graph.add(mut.note)
                if mut.note.id not in task.writes_notes:
                    task.writes_notes.append(mut.note.id)
            else:  # "replace"
                self.note_graph.replace(mut.note, by=task.id)
                if mut.note.id not in task.writes_notes:
                    task.writes_notes.append(mut.note.id)
            if self._on_note_mutation is not None:
                self._on_note_mutation(mut, task)
        for sub in result.spawned_tasks:
            sub.parent_id = task.id
            self.task_graph.add(sub)
            task.spawned_sub_tasks.append(sub.id)

    def _finish(self, task: Task) -> None:
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        logger.info(
            "done task_id=%s wrote=%d spawned=%d",
            task.id,
            len(task.writes_notes),
            len(task.spawned_sub_tasks),
        )
