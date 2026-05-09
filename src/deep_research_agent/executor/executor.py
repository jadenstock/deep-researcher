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

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..config import LocalConfig, PipelineConfig, RoutingConfig
from ..scheduler import NoteReader, TaskReader, TaskResult
from ..schemas import Task, TaskType
from ..token_usage import TokenUsageTracker
from .llm import LLMRunner, PydanticAIRunner
from .routing import select_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HandlerContext:
    """Per-call bundle handed to a task-type handler."""

    task: Task
    notes: NoteReader
    tasks: TaskReader
    model_id: str
    routing: RoutingConfig
    local: LocalConfig
    pipeline: PipelineConfig
    tracker: TokenUsageTracker
    llm: LLMRunner

    async def track(self, agent: Any, user_input: Any) -> Any:
        """Run an agent and record its token usage against this task's model.

        Thin wrapper around `agent.run(user_input)` — returns whatever
        pydantic_ai returns — but books the usage into the tracker and
        logs a structured line so every LLM call is visible in the log
        stream without needing a tracing backend.
        """
        t0 = time.monotonic()
        result = await agent.run(user_input)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        usage = result.usage() if hasattr(result, "usage") else None
        if usage is not None:
            await self.tracker.record(self.model_id, usage, task_type=self.task.type.value)
            logger.info(
                "llm_call model=%s task=%s in=%d out=%d ms=%d",
                self.model_id,
                self.task.type.value,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                elapsed_ms,
            )
        else:
            logger.info(
                "llm_call model=%s task=%s usage=unavailable ms=%d",
                self.model_id,
                self.task.type.value,
                elapsed_ms,
            )
        return result


HandlerFn = Callable[[HandlerContext], Awaitable[TaskResult]]


class UnhandledTaskType(RuntimeError):
    """No handler registered for this task type."""


class AgentExecutor:
    """Dispatcher implementing the scheduler's Executor protocol."""

    def __init__(
        self,
        routing: RoutingConfig,
        local: LocalConfig,
        pipeline: PipelineConfig | None = None,
        tracker: TokenUsageTracker | None = None,
        llm: LLMRunner | None = None,  # injectable for tests
    ) -> None:
        self.routing = routing
        self.local = local
        # Pipeline config defaults to the built-in PipelineConfig() so
        # callers that don't supply one still get working thresholds —
        # useful for tests and for code paths that instantiate an
        # executor without threading a full config through.
        self.pipeline = pipeline if pipeline is not None else PipelineConfig()
        self.tracker = tracker or TokenUsageTracker()
        self.llm: LLMRunner = llm or PydanticAIRunner(
            routing=self.routing, local=self.local, tracker=self.tracker
        )
        self._handlers: dict[TaskType, HandlerFn] = {}

    def register(self, task_type: TaskType, handler: HandlerFn) -> None:
        if task_type in self._handlers:
            raise ValueError(f"Handler already registered for {task_type.value}")
        self._handlers[task_type] = handler

    def has_handler(self, task_type: TaskType) -> bool:
        return task_type in self._handlers

    async def execute(self, task: Task, notes: NoteReader, tasks: TaskReader) -> TaskResult:
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
            tasks=tasks,
            model_id=model_id,
            routing=self.routing,
            local=self.local,
            pipeline=self.pipeline,
            tracker=self.tracker,
            llm=self.llm,
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
