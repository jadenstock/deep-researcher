"""Shared dependencies passed to every agent and tool via pydantic-ai's
`RunContext[Deps]`. One `Deps` per run; agents share it with their
sub-agents by forwarding `deps=ctx.deps` on the sub-agent invocation.

Anything the tool layer needs (search clients, memory, config, token
tracker) lives here. We construct it once at the CLI entry point and
hand it off; no globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import LocalConfig, RoutingConfig
from ..retrieval.arxiv import ArxivClient
from ..retrieval.brave import BraveClient
from ..retrieval.semantic_scholar import SemanticScholarClient
from ..token_usage import TokenUsageTracker
from .events import EventPublisher, NoOpPublisher
from .memory import NoteMemory


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
    # Per-agent structured outputs keyed on agent_id. The write_*
    # tools (tools/notes.py) populate this when an agent commits its
    # final payload; the *_run wrappers read it after agent.run()
    # returns. Concurrent sub-agents write to distinct keys so no
    # lock is needed - dict item assignment is safe under asyncio.
    outputs: dict[str, object] = field(default_factory=dict)


def build_deps(
    local: LocalConfig,
    routing: RoutingConfig,
    events: EventPublisher | None = None,
) -> Deps:
    """Assemble Deps from config. Web search is optional - some
    environments only have academic search (S2 + arXiv are
    unauthenticated or key-less). `events` defaults to a no-op; the
    server passes a publisher that feeds the UI."""
    brave = BraveClient(local.retrieval.brave_api_key) if local.retrieval.brave_api_key else None
    publisher = events or NoOpPublisher()
    return Deps(
        memory=NoteMemory(publisher=publisher),
        local=local,
        routing=routing,
        brave=brave,
        semantic_scholar=SemanticScholarClient(local.retrieval.semantic_scholar_api_key),
        arxiv=ArxivClient(),
        tracker=TokenUsageTracker(),
        events=publisher,
    )
