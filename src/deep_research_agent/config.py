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


# --- Pipeline config (YAML, tracked) ----------------------------------------
#
# Tunable thresholds and caps that govern the streaming pipeline's
# behavior. Kept separate from routing so ablation of "what to use where"
# stays decoupled from "how to run the pipeline." Every field has a safe
# default so an empty YAML file (or a missing one) still produces a
# working config.


class ScoutingConfig(BaseModel):
    """Per-strategy scout query bundle caps.

    Each strategy's `max_hits` is passed to Brave as `count` for that
    reformulation. Bigger number = more candidate URLs surfaced per
    strategy, at the cost of Brave quota + RESCORE_RELEVANCE batch size.
    """

    direct_max_hits: int = 6
    contrarian_n_reformulations: int = 2  # dropped from 3 after evidence of low yield
    contrarian_max_hits: int = 4
    time_bounded_max_hits: int = 4
    # Venue-filtered queries. Each entry is (domain, max_hits).
    venue_queries: list[tuple[str, int]] = Field(
        default_factory=lambda: [
            ("arxiv.org", 5),
            ("openreview.net", 2),
        ]
    )
    question_direct_max_hits: int = 5
    question_evidence_max_hits: int = 4
    question_review_max_hits: int = 3
    # Number of hits per verify-seed bundle (post-synthesis corroboration).
    verify_seed_max_hits: int = 5


class PromotionConfig(BaseModel):
    """Thresholds + caps for SCOUTED → FETCHED → ANALYZED promotion."""

    fetch_relevance_threshold: float = 0.30
    analyze_relevance_threshold: float = 0.35
    max_analyses_per_source: int = 5
    rescore_batch_size: int = 12


class SynthesisConfig(BaseModel):
    """Readiness gate + prompt-size caps for QUESTION_SYNTHESIZE."""

    min_analyzed_sources: int = 6
    max_qs_polls: int = 10
    max_sources_per_synthesis: int = 12


class VerificationConfig(BaseModel):
    """VERIFY_CLAIM budget + corpus-feedback behavior."""

    max_claims_per_synthesis: int = 2
    max_claims_per_run: int = 10
    # Number of independent hits pulled per verify.
    independent_hits: int = 5
    # If true, new sources surfaced during VERIFY_CLAIM are only added
    # to the corpus if at least one question is still OPEN.
    skip_seeding_after_synthesis: bool = True
    # Skip verification of claims tagged novel_to_source - a paper's own
    # proposed benchmark / method / experimental result can't be
    # corroborated by independent sources because independent sources
    # don't exist. These claims always collapse to INCONCLUSIVE; verifying
    # them just wastes budget. Set false to re-enable (e.g. if a
    # meta-analysis is expected to corroborate).
    skip_novel_claims: bool = True


class HygieneConfig(BaseModel):
    """Source-quality hygiene toggles."""

    # Reject-list URLs get Tier 5 without a fetch or LLM call. When true,
    # RESCORE_RELEVANCE refuses to promote reject-list URLs to FETCH in
    # the first place (saves the wasted fetch + classify).
    prefetch_reject_list: bool = True
    # When the analyzer rules a source off_topic for a question, zero
    # out that (source, question) relevance so further rescores don't
    # re-promote it.
    off_topic_relevance_penalty: bool = True
    # When the final report is written, emit a decision_note counting
    # SCOUTED sources that were never promoted (dead weight in the
    # corpus). Doesn't delete them - notes are immutable - just records
    # the count for the audit trail.
    record_pruned_scouted: bool = True


class ReplannerConfig(BaseModel):
    """Bounded replanner cadence + budget + stability guards."""

    cadence: int = 15
    budget: int = 3
    # Skip the cycle if fewer than this many tasks have completed since
    # the prior cycle. Guards against "nothing has changed" replans.
    min_progress_tasks: int = 6
    # Skip the cycle if no new synthesis_note has landed since the
    # prior cycle. Rationale: the replanner's main levers (escalate,
    # trigger_synthesis, spawn_scout_burst) are most useful as
    # syntheses start landing with thin evidence. Before any syntheses
    # exist, the graph is still in retrieval mode and there's little
    # for the replanner to act on.
    skip_if_no_new_synthesis: bool = True


class PipelineConfig(BaseModel):
    """Top-level tunable config for the streaming pipeline."""

    scouting: ScoutingConfig = Field(default_factory=ScoutingConfig)
    promotion: PromotionConfig = Field(default_factory=PromotionConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    hygiene: HygieneConfig = Field(default_factory=HygieneConfig)
    replanner: ReplannerConfig = Field(default_factory=ReplannerConfig)


def load_pipeline_config(path: Path | str | None = None) -> PipelineConfig:
    """Load pipeline tunables. Missing file or None path returns defaults."""
    if path is None:
        return PipelineConfig()
    p = Path(path)
    if not p.exists():
        return PipelineConfig()
    with p.open() as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return PipelineConfig.model_validate(data)


# --- Local config (TOML, gitignored) ----------------------------------------


class LLMEndpoint(BaseModel):
    api_base_url: str
    api_key: str


class RetrievalKeys(BaseModel):
    # Web search - any one of these can back the web_search tool; v0 uses
    # whichever is set, preferring brave > tavily > serper if multiple.
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    serper_api_key: str | None = None
    # Academic - optional; unauthenticated S2 works at lower rate limits.
    semantic_scholar_api_key: str | None = None
    # Unpaywall requires a contact email in every request. Unpaywall is
    # public and unauthenticated; the email is just an identifier. If
    # unset, the Unpaywall rescue step is skipped (DOIs stay as landing URLs).
    unpaywall_email: str | None = None
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
