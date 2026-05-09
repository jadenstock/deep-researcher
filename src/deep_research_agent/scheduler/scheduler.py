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
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..schemas import Note, NoteID, NoteType, Task, TaskStatus
from ..schemas.enums import DependencyType
from ..schemas.ids import TaskID
from ..schemas.task import DepEdge
from .note_graph import NoteGraph
from .task_graph import TaskGraph

# Re-exported below for handler convenience.

logger = logging.getLogger(__name__)

TaskCallback = Callable[[Task], None]
TaskDoneCallback = Callable[[Task, "TaskResult"], None]
# Task arg is None for scheduler-initiated mutations (e.g. replanner cycles).
NoteMutationCallback = Callable[["NoteMutation", Task | None], None]
# Replanner: async callable taking (task_graph, note_graph) and returning
# (list[TaskResult], decision_note). The scheduler applies the TaskResults
# through the same `_apply_result` path as regular task completions and
# persists the decision_note for UI / audit. Kept as a Callable so the
# scheduler module doesn't import from replanner (avoids cycle).
ReplannerCallback = Callable[
    [TaskGraph, NoteGraph],
    Awaitable[tuple[list["TaskResult"], Note]],
]


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


@runtime_checkable
class TaskReader(Protocol):
    """Read-only view of the task graph passed to executors.

    Used by readiness gates: a handler can inspect pending / in-progress
    tasks to decide whether to proceed or to re-emit itself with
    dependencies on the currently-pending work. Handlers MUST NOT
    mutate the task graph directly — all task mutations travel back via
    TaskResult.
    """

    def get(self, task_id: TaskID) -> Task: ...
    def all(self) -> Iterable[Task]: ...
    def __contains__(self, task_id: object) -> bool: ...


# --- Executor contract ------------------------------------------------------


class NoteMutation(BaseModel):
    """A request to create or replace a note. Applied by the scheduler."""

    kind: Literal["create", "replace"]
    note: Note


class DepEdgeAdd(BaseModel):
    """Graft a dependency edge onto an already-spawned task.

    Used when a handler needs to extend a downstream task's `depends_on`
    list after the fact — e.g. QUESTION_SYNTHESIZE spawns VERIFY_CLAIM
    tasks and grafts them onto WRITE_REPORT so the report waits for
    verification to finish.
    """

    downstream: TaskID
    upstream: TaskID
    kind: DependencyType = DependencyType.PRODUCES_CONTEXT_FOR


class TaskResult(BaseModel):
    """What an executor returns for one completed task."""

    note_mutations: list[NoteMutation] = Field(default_factory=list)
    spawned_tasks: list[Task] = Field(default_factory=list)
    added_dep_edges: list[DepEdgeAdd] = Field(default_factory=list)
    # Task IDs to abandon. Cascade: status → ABANDONED; any dep edges on
    # downstream tasks pointing at them are dropped so the downstream
    # doesn't deadlock waiting for work that will never land. In-progress
    # tasks complete their current run; PENDING tasks never start.
    abandoned_task_ids: list[TaskID] = Field(default_factory=list)
    verdict: str = ""


@runtime_checkable
class Executor(Protocol):
    """Runs one task and returns its result. No side effects on graph state."""

    async def execute(self, task: Task, notes: NoteReader, tasks: TaskReader) -> TaskResult: ...


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
        replanner: ReplannerCallback | None = None,
        replan_cadence: int = 15,
        replan_budget: int = 3,
        replan_min_progress_tasks: int = 6,
        replan_skip_if_no_new_synthesis: bool = True,
    ) -> None:
        self.task_graph = task_graph
        self.note_graph = note_graph
        self.executor = executor
        self._write_lock = asyncio.Lock()
        self._on_task_start = on_task_start
        self._on_task_done = on_task_done
        self._on_note_mutation = on_note_mutation
        self._replanner = replanner
        self._replan_cadence = replan_cadence
        self._replan_budget = replan_budget
        # Stability guards: skip a replan cycle when the graph hasn't
        # materially changed since the last one. Prevents burning budget
        # on "nothing interesting happened" replans that observationally
        # dominate runs.
        self._replan_min_progress_tasks = replan_min_progress_tasks
        self._replan_skip_if_no_new_synthesis = replan_skip_if_no_new_synthesis
        self._prev_synthesis_count = 0

    async def run(self) -> None:
        """Dispatch ready tasks until every task is terminal.

        All tasks ready in the same tick run concurrently via
        asyncio.gather. Note-graph writes stay serialized behind the
        scheduler's write lock; task-graph mutations happen under the
        same lock (via _apply_result).

        When a replanner is configured, it's invoked between ticks
        after every `replan_cadence` task completions, up to
        `replan_budget` cycles per run. Runs BETWEEN ticks (not during
        dispatch) so the graph is stable when the replanner reads it.
        """
        completed_since_replan = 0
        replans_done = 0
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
            # return_exceptions=True as defense in depth — _run_one
            # already isolates handler exceptions, but if the wrapper
            # itself raises (scheduler bug, OOM, etc.) we still want
            # the surviving tasks' results to be visible.
            tick_results = await asyncio.gather(
                *(self._run_one(t) for t in ready), return_exceptions=True
            )
            for r in tick_results:
                if isinstance(r, BaseException):
                    logger.error("scheduler_tick_exception err=%r", r)
            completed_since_replan += len(ready)
            if (
                self._replanner is not None
                and completed_since_replan >= self._replan_cadence
                and replans_done < self._replan_budget
            ):
                # Stability guards: don't burn a replan cycle on a graph
                # that hasn't materially changed. The counter resets
                # regardless so the cadence clock keeps ticking; the
                # budget only decrements if we actually run a cycle.
                if self._should_skip_replan(completed_since_replan):
                    logger.info(
                        "replan skipped (guards trip): completed=%d synthesis_count=%d",
                        completed_since_replan,
                        self._current_synthesis_count(),
                    )
                    completed_since_replan = 0
                    continue
                await self._run_replan_cycle()
                completed_since_replan = 0
                replans_done += 1
                # Snapshot synthesis count AFTER the cycle so the next
                # "no new synthesis" check compares against post-cycle state.
                self._prev_synthesis_count = self._current_synthesis_count()

    def _current_synthesis_count(self) -> int:
        """How many synthesis_notes exist right now. Cheap — just a filter.
        Used by the replan guard to detect whether the set grew since
        the prior cycle.
        """
        return len(self.note_graph.by_type(NoteType.SYNTHESIS))

    def _should_skip_replan(self, completed_since_last: int) -> bool:
        """Return True if this replan cycle should be skipped.

        Two guards, either of which trips:
        1. `completed_since_last < min_progress_tasks`: cadence fired
           but only a trickle of tasks completed — the graph hasn't
           moved. Common when many retrieval tasks are in-flight but
           tasks are completing slowly due to throttling.
        2. `skip_if_no_new_synthesis` and no new synthesis_note since
           the previous cycle. The replanner's levers (escalate,
           trigger_synthesis, abandon_subquestion) are all most useful
           in reaction to syntheses; pre-synthesis the graph has little
           for it to act on.
        """
        if completed_since_last < self._replan_min_progress_tasks:
            return True
        if self._replan_skip_if_no_new_synthesis:
            current = self._current_synthesis_count()
            if current <= self._prev_synthesis_count:
                return True
        return False

    async def _run_replan_cycle(self) -> None:
        """Invoke the replanner and apply its mutations under the write lock.

        Mutations come back as a list of TaskResult so we can reuse the
        same application path as a completed task. The decision_note is
        also applied through a synthetic TaskResult.
        """
        if self._replanner is None:  # defensive; run() already checks
            return
        logger.info("replan cycle start")
        try:
            results, decision_note = await self._replanner(self.task_graph, self.note_graph)
        except Exception as exc:
            # A replanner failure should not kill the run — just skip
            # this cycle and let the rest of the graph finish. Logged at
            # warning so it's visible but not alarming.
            logger.warning("replan cycle skipped due to replanner error: %s", exc)
            return
        decision_mutation = NoteMutation(kind="create", note=decision_note)
        async with self._write_lock:
            for r in results:
                self._apply_replan_result(r)
            # Finally, the decision note itself.
            self.note_graph.add(decision_note)
            if self._on_note_mutation is not None:
                self._on_note_mutation(decision_mutation, None)
        logger.info(
            "replan cycle applied actions=%d decision_note=%s",
            len(results),
            decision_note.id,
        )

    def _apply_replan_result(self, result: TaskResult) -> None:
        """Apply a replanner TaskResult. Mirrors `_apply_result` but without
        a completing task — the spawned tasks are new top-level work and
        the dep-edge grafts target existing downstream tasks.
        """
        for mut in result.note_mutations:
            # Replanner v3 step 2 only emits `create` mutations. `replace`
            # from the replanner path would need a TaskID for the `by`
            # attribution, which doesn't exist at the cycle level; if we
            # need cascade note-replaces later, route them through a
            # dedicated task type instead.
            if mut.kind == "create":
                self.note_graph.add(mut.note)
            else:
                logger.warning(
                    "replan ignoring note mutation kind=%s — replace not supported "
                    "from replanner path (use a task to emit the replace)",
                    mut.kind,
                )
                continue
            if self._on_note_mutation is not None:
                self._on_note_mutation(mut, None)
        for sub in result.spawned_tasks:
            self.task_graph.add(sub)
        for edge in result.added_dep_edges:
            downstream = self.task_graph.get(edge.downstream)
            if any(e.upstream == edge.upstream for e in downstream.depends_on):
                continue
            downstream.depends_on.append(DepEdge(upstream=edge.upstream, kind=edge.kind))
            logger.info(
                "replan added dep edge downstream=%s upstream=%s kind=%s",
                edge.downstream,
                edge.upstream,
                edge.kind.value,
            )
        for tid in result.abandoned_task_ids:
            dropped = self.task_graph.abandon_task(tid)
            logger.info("replan abandoned task_id=%s dropped_dep_edges=%d", tid, dropped)

    async def _run_one(self, task: Task) -> None:
        """Run one task; isolate its failures from the rest of the run.

        A handler exception marks the task ABANDONED and surfaces it
        via the on_task_done callback (so the UI shows a failed node)
        but does NOT re-raise. The task_graph already treats ABANDONED
        as "satisfied" for downstream deps, so the rest of the tick
        and subsequent ticks can proceed. The run is only failed if
        the scheduler itself can't make progress (deadlock).
        """
        self.task_graph.update_status(task.id, TaskStatus.RUNNING)
        logger.info("dispatch task_id=%s type=%s", task.id, task.type.value)
        if self._on_task_start is not None:
            self._on_task_start(task)
        try:
            result = await self.executor.execute(task, self.note_graph, self.task_graph)
        except Exception as exc:
            self.task_graph.update_status(task.id, TaskStatus.ABANDONED)
            logger.exception("task_id=%s abandoned due to exception", task.id)
            if self._on_task_done is not None:
                # Surface a synthetic failure result so the UI sees the
                # abandonment. The empty TaskResult keeps downstream
                # code (that inspects .verdict / .abandoned_task_ids)
                # safe to walk.
                failed = TaskResult(
                    verdict=f"FAILED: {type(exc).__name__}: {str(exc)[:200]}",
                )
                try:
                    self._on_task_done(task, failed)
                except Exception:
                    logger.exception("on_task_done raised for abandoned task %s", task.id)
            return
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
        for edge in result.added_dep_edges:
            downstream = self.task_graph.get(edge.downstream)
            if any(e.upstream == edge.upstream for e in downstream.depends_on):
                continue
            downstream.depends_on.append(DepEdge(upstream=edge.upstream, kind=edge.kind))
            logger.info(
                "added dep edge downstream=%s upstream=%s kind=%s",
                edge.downstream,
                edge.upstream,
                edge.kind.value,
            )
        for tid in result.abandoned_task_ids:
            dropped = self.task_graph.abandon_task(tid)
            logger.info("abandoned task_id=%s dropped_dep_edges=%d", tid, dropped)

    def _finish(self, task: Task) -> None:
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        logger.info(
            "done task_id=%s wrote=%d spawned=%d",
            task.id,
            len(task.writes_notes),
            len(task.spawned_sub_tasks),
        )
