"""Agent executor — implements the Scheduler's Executor protocol by
dispatching task types to registered handlers.

One handler per task type. The executor resolves the model via the
routing config (enforcing the cross-family invariant), then invokes the
handler with a HandlerContext that bundles the task, a read-only note
view, the resolved model_id, the full routing config, and the local
config (API endpoint + keys for tools).

Handlers themselves live in sibling modules (pattern modules for
orchestration, retrieval for search/fetch, etc.). The executor knows
nothing about individual task semantics — it just dispatches.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..config import LocalConfig, RoutingConfig
from ..scheduler import NoteReader, TaskResult
from ..schemas import Task, TaskType
from .routing import select_model


@dataclass(frozen=True)
class HandlerContext:
    """Per-call bundle handed to a task-type handler."""

    task: Task
    notes: NoteReader
    model_id: str
    routing: RoutingConfig
    local: LocalConfig


HandlerFn = Callable[[HandlerContext], Awaitable[TaskResult]]


class UnhandledTaskType(RuntimeError):
    """No handler registered for this task type."""


class AgentExecutor:
    """Dispatcher implementing the scheduler's Executor protocol."""

    def __init__(self, routing: RoutingConfig, local: LocalConfig) -> None:
        self.routing = routing
        self.local = local
        self._handlers: dict[TaskType, HandlerFn] = {}

    def register(self, task_type: TaskType, handler: HandlerFn) -> None:
        if task_type in self._handlers:
            raise ValueError(f"Handler already registered for {task_type.value}")
        self._handlers[task_type] = handler

    def has_handler(self, task_type: TaskType) -> bool:
        return task_type in self._handlers

    async def execute(self, task: Task, notes: NoteReader) -> TaskResult:
        handler = self._handlers.get(task.type)
        if handler is None:
            raise UnhandledTaskType(
                f"No handler registered for task type {task.type.value!r}. "
                f"This task type lands in a later milestone."
            )
        forbidden = self._forbidden_family(task, notes)
        model_id = select_model(
            self.routing,
            role=task.role,
            tier=task.tier,
            task_type=task.type,
            forbidden_family=forbidden,
        )
        ctx = HandlerContext(
            task=task,
            notes=notes,
            model_id=model_id,
            routing=self.routing,
            local=self.local,
        )
        return await handler(ctx)

    def _forbidden_family(self, task: Task, notes: NoteReader) -> str | None:
        """Return the model family this task must NOT route to.

        For VERIFY_CLAIM, this is the family of the ANALYZE_SOURCE that
        produced the claim being verified. Looked up via the source_note
        referenced in `task.input_refs["source_note_id"]` and the claim
        row matching `input_refs["claim_id"]`.

        Returns None (no restriction) when the provenance isn't
        available — logged as a warning rather than failing the task so
        claims from pre-v2 runs without stamped family still verify.
        """
        if task.type != TaskType.VERIFY_CLAIM:
            return None
        source_note_id = task.input_refs.get("source_note_id")
        claim_id = task.input_refs.get("claim_id")
        if not source_note_id or not claim_id:
            return None
        if source_note_id not in notes:
            return None
        src = notes.get(source_note_id)
        for c in getattr(src.metadata, "claims", []) or []:
            if c.id == claim_id:
                return c.analyzed_by_family
        return None
