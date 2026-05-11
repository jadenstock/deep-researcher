"""Shared agent-run driver.

Each `*_run` function (scout/analyst/landscape/researcher) has the same
boilerplate around `agent.iter()`: publish `on_agent_start`, set the
agent-id contextvar, iterate the run while logging nodes and
recording usage, publish `on_agent_done(ABANDONED)` on exception,
reset the contextvar. `drive_agent` captures that pattern.

The caller remains responsible for reading committed output from
wherever the agent's terminal tool put it (a QUESTION/LANDSCAPE note,
a closure-owned outbox), deciding a fallback on "no commit",
computing a verdict, and publishing `on_agent_done(DONE)` - those
parts differ per agent and keeping them in the caller makes each
`*_run` a straight-line read.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from ..schemas.enums import AgentRunStatus, RoleClass, TaskTier
from ._debug import log_run_node
from ._usage import record_run_usage
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id


async def drive_agent(
    *,
    deps: Deps,
    agent: Agent[Deps, Any],
    agent_id: str,
    agent_type: str,
    goal: str,
    tier: TaskTier,
    role: RoleClass,
    model_id: str,
    prompt: str,
    mode: str | None = None,
) -> None:
    """Drive one `agent.iter()` session with full instrumentation.

    Emits `on_agent_start`, runs the agent loop while logging nodes
    and accumulating token usage, and emits `on_agent_done(ABANDONED)`
    if the run raises. Does NOT emit `on_agent_done(DONE)` - the
    caller does that after inspecting committed output.
    """
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type=agent_type,
        goal=goal,
        tier=tier.value,
        role=role.value,
        model_id=model_id,
        mode=mode,
    )
    token = set_current_agent_id(agent_id)
    try:
        try:
            # `agent.iter()` lets the finally-block read `run.usage()`
            # when a deep tool call raises, so partial token burn on
            # crashes still lands in the shared tracker.
            async with agent.iter(prompt, deps=deps) as run:
                try:
                    async for node in run:
                        log_run_node(agent_id, node)
                finally:
                    await record_run_usage(
                        deps,
                        run.usage(),
                        agent_id=agent_id,
                        agent_type=agent_type,
                        model_id=model_id,
                    )
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type=agent_type,
                status=AgentRunStatus.ABANDONED,
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise
    finally:
        reset_current_agent_id(token)
