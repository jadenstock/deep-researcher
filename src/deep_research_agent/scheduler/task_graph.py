"""Task graph — owns task state and ready-set computation.

All access to task state goes through this class. Mutation semantics
(cascade rules for merge / split / abandon / add-edge per ADR 0009) will
land here as they're implemented; v0 supports only add + status update.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..schemas import Task, TaskID, TaskStatus


class TaskGraph:
    """In-memory task graph.

    For v0 this is a flat dict keyed on TaskID. A persistence adapter can
    be swapped in behind the same interface without touching callers.
    """

    def __init__(self) -> None:
        self._tasks: dict[TaskID, Task] = {}

    def add(self, task: Task) -> TaskID:
        if task.id in self._tasks:
            raise ValueError(f"Task {task.id} already in graph")
        self._tasks[task.id] = task
        return task.id

    def get(self, task_id: TaskID) -> Task:
        return self._tasks[task_id]

    def all(self) -> Iterable[Task]:
        return self._tasks.values()

    def update_status(self, task_id: TaskID, status: TaskStatus) -> None:
        self._tasks[task_id].status = status

    def abandon_task(self, task_id: TaskID) -> int:
        """Mark a task ABANDONED and drop all dep edges pointing at it.

        Per ADR 0009 cascade: downstream tasks that were waiting on this
        task shouldn't deadlock. Returns the number of dep edges
        removed for observability.

        If the task is already in a terminal state (DONE / ABANDONED /
        ESCALATED), this is a no-op on the task itself but still strips
        dangling edges from downstream deps as a defensive measure.
        """
        if task_id in self._tasks:
            t = self._tasks[task_id]
            if t.status not in {TaskStatus.DONE, TaskStatus.ABANDONED, TaskStatus.ESCALATED}:
                t.status = TaskStatus.ABANDONED
        dropped = 0
        for t in self._tasks.values():
            before = len(t.depends_on)
            t.depends_on = [e for e in t.depends_on if e.upstream != task_id]
            dropped += before - len(t.depends_on)
        return dropped

    def get_ready(self) -> list[Task]:
        """Return the PENDING tasks whose dependencies are satisfied.

        Retrieval-phase tasks (dep_scope.retrieval_ignores=True) run
        regardless of upstream deps — they retrieve evidence that synthesis
        tasks will later reason over (ADR 0006). Synthesis-phase tasks
        wait until every upstream task is DONE or satisfied-equivalent
        (ABANDONED upstream counts as satisfied — downstream shouldn't
        block on work that won't complete, per ADR 0009 cascade).

        BLOCKED_ON_SPLIT tasks are not ready; they resume only after the
        replanner re-assigns them via a status transition back to PENDING.
        """
        ready: list[Task] = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            if t.dep_scope.retrieval_ignores or self._deps_done(t):
                ready.append(t)
        return ready

    def _deps_done(self, task: Task) -> bool:
        # ABANDONED counts as satisfied for dep purposes (ADR 0009): the
        # upstream work won't produce, downstream shouldn't deadlock.
        satisfied = {TaskStatus.DONE, TaskStatus.ABANDONED, TaskStatus.ESCALATED}
        return all(self._tasks[edge.upstream].status in satisfied for edge in task.depends_on)

    def all_terminal(self) -> bool:
        terminal = {TaskStatus.DONE, TaskStatus.ESCALATED, TaskStatus.ABANDONED}
        return all(t.status in terminal for t in self._tasks.values())

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._tasks
