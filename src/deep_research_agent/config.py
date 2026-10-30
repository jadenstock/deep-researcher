"""Config loaders.

Two config files per run:

1. **Routing config** (YAML, tracked in `config/`): maps (role, tier) to a
   model identifier. Policy-level; one file per ablation configuration.
2. **Local config** (TOML, NOT tracked: `config/local.toml`): API endpoints
   and secrets. One file per developer / machine.

The routing config is policy ("use Claude for generative, GPT for
judgment"). The local config is infrastructure ("send all traffic to this
router endpoint with this API key"). They compose at runtime: the
executor resolves a model_id via routing, then invokes it through the
endpoint from local.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .schemas.enums import RoleClass, TaskTier

# --- Routing config (YAML, tracked) -----------------------------------------


class TierRouting(BaseModel):
    generative: str
    judgment: str
    cheap_deterministic: str


class RoutingConfig(BaseModel):
    name: str
    description: str = ""
    tiers: dict[TaskTier, TierRouting]

    def model_id_for(self, role: RoleClass, tier: TaskTier) -> str:
        return getattr(self.tiers[tier], role.value)

    @staticmethod
    def router_name(model_id: str) -> str:
        """Strip the family prefix to get the name expected by the router.

        The full identifier 'anthropic/claude-opus-5-5' carries family
        information for the ADR 0008 invariant check; the router itself
        expects the bare model name 'claude-opus-5-5'. An optional
        ':<effort>' suffix (see `reasoning_effort`) is stripped too.
        """
        name = model_id.split("/", 1)[1] if "/" in model_id else model_id
        return name.split(":", 1)[0]

    @staticmethod
    def reasoning_effort(model_id: str) -> str | None:
        """Read the optional reasoning-effort suffix off a model_id.

        'openai/gpt-6-luna:high' -> 'high'; no suffix -> None (router
        default). Keeping effort inside the model_id string lets the YAML,
        UI dropdowns, and per-run overrides carry it without a schema change.
        """
        return model_id.rsplit(":", 1)[1] if ":" in model_id else None


def load_routing_config(path: Path | str) -> RoutingConfig:
    p = Path(path)
    with p.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return RoutingConfig.model_validate(data)


# --- Local config (TOML, gitignored) ----------------------------------------


class LLMEndpoint(BaseModel):
    api_base_url: str
    api_key: str


class RetrievalKeys(BaseModel):
    # Web search. Only Brave is wired up currently.
    brave_api_key: str | None = None
    # Academic - optional; unauthenticated S2 works at lower rate limits.
    semantic_scholar_api_key: str | None = None
    # Min interval (seconds) between Brave Search calls. Free tier enforces
    # 1 req/s with a strict sliding window - 1.05s cuts it too close in
    # practice, 1.5s is safe. Paid plans can drop to ~0.05 (20 req/s) or
    # ~0.02 (50 req/s).
    brave_min_interval_s: float = 1.5
    # Min interval (seconds) between Semantic Scholar calls. Unauthenticated
    # is ~100 req / 5min (~0.33/s, so 3.0s); authenticated plans typically
    # allow 1/s per key. If None, the client picks a default based on
    # whether semantic_scholar_api_key is set.
    semantic_scholar_min_interval_s: float | None = None
    # Min interval (seconds) between arXiv queries. arXiv's published
    # guideline is 1 req / 3s on the public endpoint.
    arxiv_min_interval_s: float = 3.0


class LocalConfig(BaseModel):
    llm: LLMEndpoint
    retrieval: RetrievalKeys = Field(default_factory=RetrievalKeys)


def load_local_config(path: Path | str = "config/local.toml") -> LocalConfig:
    p = Path(path)
    with p.open("rb") as f:
        data = tomllib.load(f)
    return LocalConfig.model_validate(data)
