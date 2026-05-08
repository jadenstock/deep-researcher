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

    def get_ready(self) -> list[Task]:
        """Return the PENDING tasks whose dependencies are satisfied.

        Retrieval-phase tasks (dep_scope.retrieval_ignores=True) run
        regardless of upstream deps — they retrieve evidence that synthesis
        tasks will later reason over (ADR 0006). Synthesis-phase tasks
        wait until every upstream task is DONE.

        Note on v0 simplification: this implementation filters the ready
        set but does not transition tasks into BLOCKED_ON_SYNTHESIS_DEP.
        Explicit blocked-status transitions arrive alongside the replanner
        (v3), when the distinction becomes visible in the note graph for
        user-facing diagnostics.
        """
        ready: list[Task] = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            if t.dep_scope.retrieval_ignores or self._deps_done(t):
                ready.append(t)
        return ready

    def _deps_done(self, task: Task) -> bool:
        return all(self._tasks[edge.upstream].status == TaskStatus.DONE for edge in task.depends_on)

    def all_terminal(self) -> bool:
        terminal = {TaskStatus.DONE, TaskStatus.ESCALATED, TaskStatus.ABANDONED}
        return all(t.status in terminal for t in self._tasks.values())

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._tasks
