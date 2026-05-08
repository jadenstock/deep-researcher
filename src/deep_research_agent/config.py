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

from .schemas.enums import RoleClass, TaskTier, TaskType

# --- Routing config (YAML, tracked) -----------------------------------------


class TierRouting(BaseModel):
    generative: str
    judgment: str
    cheap_deterministic: str


class CrossFamilyInvariant(BaseModel):
    enabled: bool = True
    applies_to: list[TaskType] = Field(default_factory=lambda: [TaskType.VERIFY_CLAIM])


class RoutingConfig(BaseModel):
    name: str
    description: str = ""
    tiers: dict[TaskTier, TierRouting]
    cross_family_invariant: CrossFamilyInvariant = Field(default_factory=CrossFamilyInvariant)

    def model_id_for(self, role: RoleClass, tier: TaskTier) -> str:
        return getattr(self.tiers[tier], role.value)

    @staticmethod
    def family_of(model_id: str) -> str:
        """Family := part before '/' in a 'family/model' identifier."""
        return model_id.split("/", 1)[0] if "/" in model_id else model_id

    @staticmethod
    def router_name(model_id: str) -> str:
        """Strip the family prefix to get the name expected by the router.

        The full identifier 'anthropic/claude-opus-4-7' carries family
        information for the ADR 0008 invariant check; the router itself
        expects the bare model name 'claude-opus-4-7'.
        """
        return model_id.split("/", 1)[1] if "/" in model_id else model_id


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
    # Web search — any one of these can back the web_search tool; v0 uses
    # whichever is set, preferring brave > tavily > serper if multiple.
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    serper_api_key: str | None = None
    # Academic — optional; unauthenticated S2 works at lower rate limits.
    semantic_scholar_api_key: str | None = None
    # Min interval (seconds) between Brave Search calls. Free tier enforces
    # 1 req/s with a strict sliding window — 1.05s cuts it too close in
    # practice, 1.5s is safe. Paid plans can drop to ~0.05 (20 req/s) or
    # ~0.02 (50 req/s).
    brave_min_interval_s: float = 1.5


class ObservabilityKeys(BaseModel):
    logfire_token: str | None = None


class LocalConfig(BaseModel):
    llm: LLMEndpoint
    retrieval: RetrievalKeys = Field(default_factory=RetrievalKeys)
    observability: ObservabilityKeys = Field(default_factory=ObservabilityKeys)


def load_local_config(path: Path | str = "config/local.toml") -> LocalConfig:
    p = Path(path)
    with p.open("rb") as f:
        data = tomllib.load(f)
    return LocalConfig.model_validate(data)
