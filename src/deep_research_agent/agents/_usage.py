"""Helper shared by the three agent-run wrappers.

Each wrapper (landscape / researcher / analyst) does exactly the same
thing after its `agent.iter(...)` block exits: record the RunUsage into
the shared per-run `TokenUsageTracker` and emit a `token_usage` event
so the UI can update its running total.

Kept in its own module to avoid triplicating the field extraction +
zero-guard logic, and to keep the wrappers readable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..schemas.enums import AgentType

if TYPE_CHECKING:
    from .deps import Deps

logger = logging.getLogger(__name__)


async def record_run_usage(
    deps: Deps,
    usage: Any,
    *,
    agent_id: str,
    agent_type: AgentType,
    model_id: str,
) -> None:
    """Record a RunUsage into the tracker and emit a UI event.

    Safe to call with `usage=None` (e.g., if `run.usage()` raised) or
    with a RunUsage that has no values; either way we short-circuit
    and do nothing.
    """
    if usage is None:
        return
    has_values = getattr(usage, "has_values", None)
    if callable(has_values) and not has_values():
        return

    try:
        deltas = await deps.tracker.record(model_id=model_id, usage=usage, task_type=agent_type)
    except Exception:
        logger.exception(
            "token tracker record failed agent_id=%s model=%s",
            agent_id,
            model_id,
        )
        return

    try:
        deps.events.on_token_usage(
            agent_id=agent_id,
            agent_type=agent_type,
            model_id=model_id,
            input_tokens=deltas["input_tokens"],
            output_tokens=deltas["output_tokens"],
            cache_read_tokens=deltas["cache_read_tokens"],
            cache_write_tokens=deltas["cache_write_tokens"],
        )
    except Exception:
        logger.exception(
            "token_usage event emit failed agent_id=%s",
            agent_id,
        )


def publish_usage_progress(
    deps: Deps,
    usage: Any,
    *,
    agent_id: str,
    agent_type: AgentType,
    model_id: str,
) -> None:
    """Emit an agent's running token totals mid-run (after each step).

    The tracker is only updated once, at the end of the agent's run; this
    just lets listeners such as the progress file show live spend for
    long-running agents like the researcher.
    """
    try:
        deps.events.on_usage_progress(
            agent_id=agent_id,
            agent_type=agent_type,
            model_id=model_id,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
        )
    except Exception:
        logger.exception("usage progress emit failed agent_id=%s", agent_id)
