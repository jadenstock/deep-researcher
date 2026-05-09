"""LLM Runner seam.

One interface for every LLM call in the system. The runner owns:

- `(role, tier) → model_id` resolution via RoutingConfig
- Cross-family invariant enforcement (ADR-0008)
- Agent construction (hidden from callers)
- Token usage tracking and structured logging
- Returning typed output wrapped in LLMResult

Callers pass role + tier + output_type + prompts; they do not know about
pydantic_ai, make_model, or RoutingConfig internals. Tests replace the
runner with a FakeLLMRunner that returns scripted output.

Phase-1 scope: this module is additive. Existing handlers continue to
use `ctx.track(Agent(...))` until Phase 2. Only the tier classifier
migrates here in Phase 1.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig, RoutingConfig
from ..schemas.enums import RoleClass, TaskTier, TaskType
from ..token_usage import TokenUsageTracker
from .routing import select_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult[T]:
    """Typed output + resolved model_id + elapsed_ms. Usage is already
    booked into the tracker by the runner — callers don't need to."""

    output: T
    model_id: str
    elapsed_ms: int


class LLMRunner(Protocol):
    async def run[T](
        self,
        *,
        role: RoleClass,
        tier: TaskTier,
        output_type: type[T],
        system_prompt: str,
        user_prompt: str,
        task_type: str | TaskType | None = None,
        forbidden_family: str | None = None,
        script_key: str | None = None,  # ignored by real runner; used by fakes
    ) -> LLMResult[T]: ...


AgentFactory = Callable[[str, LocalConfig, type, str], Any]
"""Hook so tests can replace Agent construction. Signature:
    (model_id, local, output_type, system_prompt) -> Agent-like with .run()"""


def _default_agent_factory(
    model_id: str, local: LocalConfig, output_type: type, system_prompt: str
) -> Any:
    return Agent(
        make_model(model_id, local),
        output_type=output_type,
        system_prompt=system_prompt,
    )


def _coerce_task_type(task_type: str | TaskType | None) -> TaskType | None:
    """Best-effort coercion. Unknown strings (e.g. sub-step labels like
    'TIER_CLASSIFY' that aren't in TaskType) return None — callers that
    need a concrete TaskType substitute a sentinel."""
    if task_type is None:
        return None
    if isinstance(task_type, TaskType):
        return task_type
    try:
        return TaskType(task_type)
    except ValueError:
        return None


@dataclass
class PydanticAIRunner:
    """Real LLMRunner — wraps pydantic_ai.Agent."""

    routing: RoutingConfig
    local: LocalConfig
    tracker: TokenUsageTracker | None = None
    agent_factory: AgentFactory = _default_agent_factory

    async def run[T](
        self,
        *,
        role: RoleClass,
        tier: TaskTier,
        output_type: type[T],
        system_prompt: str,
        user_prompt: str,
        task_type: str | TaskType | None = None,
        forbidden_family: str | None = None,
        script_key: str | None = None,  # unused by real runner
    ) -> LLMResult[T]:
        del script_key  # accepted for protocol compatibility; fakes only
        tt = _coerce_task_type(task_type)
        # select_model requires a TaskType; when we don't have one (unknown
        # label), use ANALYZE_SOURCE as a safe sentinel — it's never in the
        # cross-family invariant list, so no spurious rejection.
        sentinel = tt if tt is not None else TaskType.ANALYZE_SOURCE
        model_id = select_model(
            self.routing,
            role=role,
            tier=tier,
            task_type=sentinel,
            forbidden_family=forbidden_family,
        )
        agent = self.agent_factory(model_id, self.local, output_type, system_prompt)
        t0 = time.monotonic()
        r = await agent.run(user_prompt)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        usage = r.usage() if hasattr(r, "usage") else None
        task_label = tt.value if tt is not None else (str(task_type) if task_type else "UNKNOWN")
        if usage is not None and self.tracker is not None:
            await self.tracker.record(model_id, usage, task_type=task_label)
            logger.info(
                "llm_call model=%s task=%s in=%d out=%d ms=%d",
                model_id,
                task_label,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                elapsed_ms,
            )
        else:
            logger.info(
                "llm_call model=%s task=%s usage=unavailable ms=%d",
                model_id,
                task_label,
                elapsed_ms,
            )
        return LLMResult(output=r.output, model_id=model_id, elapsed_ms=elapsed_ms)
