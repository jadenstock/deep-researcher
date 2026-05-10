"""The `scout` tool - analyst dispatches a scout sub-agent from here.

Structurally parallel to `investigate_question` in researcher.py:
the tool lives in the parent agent's tool set, decrements a per-run
budget, and invokes the child agent's *_run function. The child's
events and token usage are tagged under its own agent_id.
"""

from __future__ import annotations

import logging

from pydantic_ai import ModelRetry, RunContext

from ..deps import Deps
from ..events import instrumented
from ..schemas import ScoutResult
from ..scout import scout_run

logger = logging.getLogger(__name__)


@instrumented
async def scout(ctx: RunContext[Deps], request: str) -> ScoutResult:
    """Dispatch a scout sub-agent to retrieve + triage sources for an angle.

    The scout runs search → create_source_note → scout_fetch (skim) in
    its own internal loop (2-3 rounds). It writes cleaned page content
    onto source notes' `content` field so you can deep-read via
    `load_note(source_id)` later. Returns a pre-digested sourcelist +
    coverage note - you never eat raw SERP results or 404 errors in
    your own context.

    Run multiple `scout()` calls in parallel in one turn with distinct
    angles of your assigned question - the analyst framework
    dispatches them concurrently.

    Args:
      request: Natural-language description of the angle you want
        scouted. Be specific: "find methodology critiques of MMLU,
        especially from 2023-2025" is better than "MMLU". The scout
        plans its own queries from this request.

    Returns ScoutResult with:
      - sources: list of ScoutedSource (source_id, url, title,
        tier_guess, relevance_guess, preview). `preview` is a short
        excerpt from the scout's skim; full cleaned content lives on
        `note.content` and is retrievable via `load_note(source_id)`.
      - coverage_note: one-paragraph summary of what the scout
        searched and where coverage is thin. Use it to decide whether
        another scout dispatch on a different angle is warranted.

    Budget: capped at 4 scout dispatches per analyst run. When the
    budget is exhausted, this tool raises ModelRetry - stop
    dispatching scouts and commit your answer with the evidence you
    already have.
    """
    budget = ctx.deps.outputs.get("__scout_budget__")
    if isinstance(budget, int) and budget <= 0:
        raise ModelRetry(
            "scout dispatch budget exhausted (0 remaining). Stop dispatching "
            "scouts; deep-read the sources you already have and commit your "
            "answer with answer_question."
        )
    if isinstance(budget, int):
        ctx.deps.outputs["__scout_budget__"] = budget - 1

    return await scout_run(ctx.deps, request)
