"""Shared node-level logging for agent run loops.

Each agent wrapper drives `agent.iter()` with `async for _ in run: pass`.
Wrapping that yielded node with `log_run_node` surfaces `finish_reason` and
tool-call arg shape at the SDK-to-tool boundary — the point where truncated
model output turns into Pydantic ValidationErrors and where the openai client
logs don't capture the response body.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import messages as _messages
from pydantic_ai._agent_graph import CallToolsNode

logger = logging.getLogger(__name__)


def _summarize_part(part: Any) -> str:
    if isinstance(part, _messages.ToolCallPart):
        args = part.args
        if isinstance(args, dict):
            keys = list(args.keys())
            sizes = {
                k: (len(v) if isinstance(v, (str, list, dict)) else type(v).__name__)
                for k, v in args.items()
            }
            return f"ToolCall({part.tool_name}, keys={keys}, sizes={sizes})"
        raw_len = len(args) if isinstance(args, str) else "n/a"
        return f"ToolCall({part.tool_name}, args_raw_len={raw_len})"
    if isinstance(part, _messages.TextPart):
        return f"Text(len={len(part.content)})"
    if isinstance(part, _messages.ThinkingPart):
        return f"Thinking(len={len(part.content)})"
    return type(part).__name__


def log_run_node(agent_id: str, node: Any) -> None:
    """Log diagnostic info for a single node yielded by `agent.iter()`.

    Quiet by default. Escalates to WARNING when `finish_reason == 'length'`
    (i.e. max_tokens truncation) because that's the failure mode that
    produces confusing "missing required field" ValidationErrors downstream.
    """
    if not isinstance(node, CallToolsNode):
        return
    mr = node.model_response
    finish = mr.finish_reason
    parts_summary = [_summarize_part(p) for p in mr.parts]

    if finish == "length":
        logger.warning(
            "model response truncated (finish_reason=length) agent_id=%s parts=%s - "
            "tool-call args likely missing fields; raise max_tokens or shorten prompt",
            agent_id,
            parts_summary,
        )
    else:
        logger.debug(
            "model response agent_id=%s finish_reason=%s parts=%s",
            agent_id,
            finish,
            parts_summary,
        )
