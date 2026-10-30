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

from ..schemas.enums import AgentRunStatus, AgentType, RoleClass, TaskTier
from ._debug import log_run_node
from ._usage import publish_usage_progress, record_run_usage
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id


async def drive_agent(
    *,
    deps: Deps,
    agent: Agent[Deps, Any],
    agent_id: str,
    agent_type: AgentType,
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
        tier=tier,
        role=role,
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
                        publish_usage_progress(
                            deps,
                            run.usage(),
                            agent_id=agent_id,
                            agent_type=agent_type,
                            model_id=model_id,
                        )
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


async def drive_agent_with_history(
    *,
    deps: Deps,
    agent: Agent[Deps, Any],
    agent_id: str,
    agent_type: AgentType,
    goal: str,
    tier: TaskTier,
    role: RoleClass,
    model_id: str,
    prompt: str,
    message_history: list[Any] | None = None,
    mode: str | None = None,
) -> tuple[Any, list[Any]]:
    """Variant of drive_agent that threads a chat history through.

    Used by the chat agent across multi-turn conversations: the
    caller persists the returned `messages` and feeds them back on
    the next turn. Returns `(output, all_messages)` where `output`
    is the agent's final response (whatever pydantic-ai produces as
    `run.result.output`) and `all_messages` is the post-turn message
    list to carry forward.
    """
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type=agent_type,
        goal=goal,
        tier=tier,
        role=role,
        model_id=model_id,
        mode=mode,
    )
    token = set_current_agent_id(agent_id)
    try:
        try:
            async with agent.iter(prompt, deps=deps, message_history=message_history) as run:
                try:
                    async for node in run:
                        log_run_node(agent_id, node)
                        publish_usage_progress(
                            deps,
                            run.usage(),
                            agent_id=agent_id,
                            agent_type=agent_type,
                            model_id=model_id,
                        )
                finally:
                    await record_run_usage(
                        deps,
                        run.usage(),
                        agent_id=agent_id,
                        agent_type=agent_type,
                        model_id=model_id,
                    )
                # `run.all_messages()` is canonical on the AgentRun and
                # returns the full history (incl. prior turns threaded in
                # via message_history). `run.result.all_messages()` does
                # NOT — it returns only the new messages from this run.
                output = run.result.output if run.result is not None else None
                messages = list(run.all_messages())
                return output, messages
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
