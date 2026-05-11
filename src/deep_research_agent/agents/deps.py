"""Shared dependencies passed to every agent and tool via pydantic-ai's
`RunContext[Deps]`. One `Deps` per run; agents share it with their
sub-agents by forwarding `deps=ctx.deps` on the sub-agent invocation.

Anything the tool layer needs (search clients, memory, config, token
tracker) lives here. We construct it once at the CLI entry point and
hand it off; no globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..config import LocalConfig, RoutingConfig
from ..retrieval.arxiv import ArxivClient
from ..retrieval.brave import BraveClient
from ..retrieval.semantic_scholar import SemanticScholarClient
from ..schemas.ids import NoteID
from ..token_usage import TokenUsageTracker
from .events import EventPublisher, NoOpPublisher
from .memory import NoteMemory


@dataclass
class RunState:
    """Mutable per-run state that tools and agent drivers read and write.

    Kept separate from `Deps` so `Deps` itself stays a stable container
    of clients and config; `RunState` holds the pieces that change
    during the run.

    Fields:
      - `root_question_id`: set by the researcher on entry so the
        investigate_question tool can parent-link sub-questions and
        get_research_state can surface the root separately.
      - `analyst_budget` / `scout_budget`: dispatch caps. `None` means
        "no budget configured" (tool skips the check); an int is the
        remaining count. Set by the wrapping `*_run` on entry,
        decremented by the dispatching tool.
      - `agent_outputs`: typed payload per agent_id. TERMINAL tools
        (answer_question, commit_scout_result, write_landscape_brief)
        stash their structured output here; the wrapping `*_run`
        reads it after the agent finishes. Concurrent sub-agents
        write to distinct keys so no lock is needed.
    """

    root_question_id: NoteID | None = None
    analyst_budget: int | None = None
    scout_budget: int | None = None
    agent_outputs: dict[str, object] = field(default_factory=dict)


@dataclass
class Deps:
    memory: NoteMemory
    local: LocalConfig
    routing: RoutingConfig
    brave: BraveClient | None  # None if no brave_api_key configured
    semantic_scholar: SemanticScholarClient
    arxiv: ArxivClient
    tracker: TokenUsageTracker
    events: EventPublisher
    http_client: httpx.AsyncClient
    state: RunState = field(default_factory=RunState)


def build_deps(
    local: LocalConfig,
    routing: RoutingConfig,
    events: EventPublisher | None = None,
) -> Deps:
    """Assemble Deps from config. Web search is optional - some
    environments only have academic search (S2 + arXiv are
    unauthenticated or key-less). `events` defaults to a no-op; the
    server passes a publisher that feeds the UI.

    The returned Deps owns an `http_client` shared across retrieval
    clients. Callers are responsible for calling `close_deps(deps)` in
    a finally block to release the connection pool.
    """
    # One pooled client per run: avoids TCP+TLS handshake per request
    # across all retrieval providers (Brave, S2, arXiv, fetcher).
    http_client = httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=20))
    brave = (
        BraveClient(http_client, local.retrieval.brave_api_key)
        if local.retrieval.brave_api_key
        else None
    )
    publisher = events or NoOpPublisher()
    return Deps(
        memory=NoteMemory(publisher=publisher),
        local=local,
        routing=routing,
        brave=brave,
        semantic_scholar=SemanticScholarClient(
            http_client, local.retrieval.semantic_scholar_api_key
        ),
        arxiv=ArxivClient(http_client),
        tracker=TokenUsageTracker(),
        events=publisher,
        http_client=http_client,
    )


async def close_deps(deps: Deps) -> None:
    """Release resources owned by `deps`. Idempotent."""
    await deps.http_client.aclose()
