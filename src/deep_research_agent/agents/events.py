"""Event publisher protocol + tool/agent instrumentation helpers.

Agents and the note memory call into an `EventPublisher` as
significant things happen: agent starts/ends, tool calls begin/end,
notes are created or mutated. The default publisher is a no-op, so
the CLI path costs nothing; the server wires a concrete publisher
that translates these calls into UI-bound events (see
`server/runner.py`).

The module also defines `_CURRENT_AGENT_ID` - a `ContextVar` that
agent run functions set before invoking their agent, and that the
`@instrumented` tool decorator reads to tag tool-call events with
the right parent. contextvars propagate cleanly across async task
chains (including `asyncio.gather`, which is how pydantic-ai
dispatches parallel tool calls), so each sub-agent's tools see their
own agent_id, not the researcher's.
"""

from __future__ import annotations

import contextvars
import functools
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ..schemas.enums import AgentRunStatus, AgentType, RoleClass, TaskTier
from ..schemas.note import Note

# Scoped per asyncio task. Each agent run function sets this at entry;
# tools read it to know which parent agent their call belongs to.
_CURRENT_AGENT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dra_current_agent_id", default=None
)


def current_agent_id() -> str | None:
    """Read the agent_id of the currently-running agent in this async task."""
    return _CURRENT_AGENT_ID.get()


def set_current_agent_id(agent_id: str) -> contextvars.Token[str | None]:
    """Set the current agent_id; returns a token for later `reset()`."""
    return _CURRENT_AGENT_ID.set(agent_id)


def reset_current_agent_id(token: contextvars.Token[str | None]) -> None:
    _CURRENT_AGENT_ID.reset(token)


class EventPublisher(Protocol):
    def on_agent_start(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        goal: str,
        tier: TaskTier,
        role: RoleClass,
        model_id: str | None,
        mode: str | None = None,
    ) -> None: ...

    def on_agent_done(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        status: AgentRunStatus,
        verdict: str,
    ) -> None: ...

    def on_note_created(self, note: Note) -> None: ...

    def on_note_replaced(self, note: Note) -> None: ...

    def on_tool_start(
        self,
        *,
        agent_id: str,
        tool_call_id: str,
        tool: str,
        summary: str,
    ) -> None: ...

    def on_tool_end(
        self,
        *,
        agent_id: str,
        tool_call_id: str,
        tool: str,
        status: str,
        summary: str,
        duration_ms: int,
    ) -> None: ...

    def on_token_usage(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None: ...


class NoOpPublisher:
    """Default publisher - swallow every event. Used by the CLI path
    where there's no UI to feed."""

    def on_agent_start(self, **_: object) -> None:  # pragma: no cover
        pass

    def on_agent_done(self, **_: object) -> None:  # pragma: no cover
        pass

    def on_note_created(self, note: Note) -> None:  # pragma: no cover
        del note

    def on_note_replaced(self, note: Note) -> None:  # pragma: no cover
        del note

    def on_tool_start(self, **_: object) -> None:  # pragma: no cover
        pass

    def on_tool_end(self, **_: object) -> None:  # pragma: no cover
        pass

    def on_token_usage(self, **_: object) -> None:  # pragma: no cover
        pass


# --- Tool instrumentation --------------------------------------------------


def _arg_summary(args: tuple, kwargs: dict) -> str:
    """Best-effort single-line summary of a tool call's inputs.

    Picks the first non-empty string-ish argument, truncated. Good
    enough for a UI ticker; not trying to be a full trace."""
    # Skip `ctx` which is positional arg 0 on every tool.
    for v in args[1:]:
        if isinstance(v, str) and v:
            return v[:100]
    for _, v in kwargs.items():
        if isinstance(v, str) and v:
            return v[:100]
    return ""


def _result_summary(result: Any) -> str:
    if result is None:
        return "ok"
    if isinstance(result, list):
        return f"{len(result)} item(s)"
    if isinstance(result, dict):
        # Tool-return dicts (e.g. load_note) - surface an id or error.
        if "error" in result:
            return f"error: {result['error']}"[:100]
        if "id" in result:
            return str(result["id"])[:100]
        return f"{len(result)} field(s)"
    if isinstance(result, str):
        return result[:100]
    # NoteID / typed scalars - repr their string form.
    return str(result)[:100]


def instrumented[F: Callable[..., Awaitable[Any]]](func: F) -> F:
    """Wrap an async agent tool to publish tool_call_start/end events.

    Events are tagged with `agent_id` from the `_CURRENT_AGENT_ID`
    contextvar (set by each agent run function). If no agent_id is
    set (e.g. direct tool invocation from a test), no events are
    emitted - the tool just runs.

    Pydantic-ai inspects the wrapped function's signature to build
    the tool's JSON schema; `functools.wraps` preserves it.
    """

    @functools.wraps(func)
    async def wrapped(ctx: Any, *args: Any, **kwargs: Any) -> Any:
        agent_id = current_agent_id()
        tool_call_id = f"tc-{uuid.uuid4().hex[:8]}"
        # Skip the implicit `ctx` positional when summarizing.
        arg_summary = _arg_summary((ctx, *args), kwargs)
        publisher: EventPublisher | None = getattr(getattr(ctx, "deps", None), "events", None)
        if agent_id and publisher is not None:
            publisher.on_tool_start(
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                tool=func.__name__,
                summary=arg_summary,
            )
        t0 = time.monotonic()
        try:
            result = await func(ctx, *args, **kwargs)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            if agent_id and publisher is not None:
                publisher.on_tool_end(
                    agent_id=agent_id,
                    tool_call_id=tool_call_id,
                    tool=func.__name__,
                    status="error",
                    summary=f"{type(exc).__name__}: {exc}"[:140],
                    duration_ms=duration_ms,
                )
            raise
        duration_ms = int((time.monotonic() - t0) * 1000)
        if agent_id and publisher is not None:
            publisher.on_tool_end(
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                tool=func.__name__,
                status="ok",
                summary=_result_summary(result),
                duration_ms=duration_ms,
            )
        return result

    return wrapped  # type: ignore[return-value]
