"""Per-run tunable knobs (budgets + model overrides).

One `RunConfig` per run, attached to `Deps`. Read once at agent-build
time inside `build_researcher` / `build_analyst` / `build_scout`; no
live reconfiguration mid-run.

Defaults live here so both the CLI (no API payload) and the server
(optional API payload) share a single source of truth. The server
exposes the defaults via `GET /api/config/defaults` so the UI can
populate sliders without hardcoding them.

Model overrides are applied by `apply_to_routing(routing)` which
returns a *new* `RoutingConfig` with the requested (tier, role) slots
swapped. Agent code keeps resolving models via
`deps.routing.model_id_for(role, tier)` — it never needs to know an
override happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import RoutingConfig, TierRouting
from ..schemas.enums import RoleClass, TaskTier

# Budget defaults. These are the ceilings the current prompts assume,
# so changing them requires no prompt rewrite for the agent to behave
# sanely — the numbers just flow through.
DEFAULT_ANALYST_BUDGET = 12
DEFAULT_SCOUT_BUDGET_PER_ANALYST = 6
DEFAULT_SCOUT_SEARCH_BUDGET = 16

# UI slider ranges. Kept here so `GET /api/config/defaults` is the
# single source of truth for both the defaults and the allowed range.
ANALYST_BUDGET_RANGE = (2, 16)
SCOUT_BUDGET_RANGE = (1, 8)
SCOUT_SEARCH_BUDGET_RANGE = (3, 20)

# Curated model catalog for the UI dropdowns. Anything not in this list
# is still acceptable via the API (arbitrary string), but the UI only
# surfaces these options. Family prefix is required (ADR 0008 invariant
# reads the prefix at runtime).
MODEL_CATALOG: dict[RoleClass, list[str]] = {
    RoleClass.GENERATIVE: [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-opus-4-7",
    ],
    RoleClass.JUDGMENT: [
        "openai/gpt-5.2",
        "openai/gpt-5.4",
        "openai/gpt-5.5",
    ],
    RoleClass.CHEAP_DETERMINISTIC: [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-6",
    ],
}


@dataclass(frozen=True)
class RunConfig:
    """Run-scoped knobs. All fields have defaults so the CLI never
    needs to construct one explicitly.

    `model_overrides` maps (tier, role) to a full `family/model`
    identifier. Keys not present in the dict fall through to the
    routing YAML's defaults. `apply_to_routing` performs the merge.
    """

    analyst_budget: int = DEFAULT_ANALYST_BUDGET
    scout_budget_per_analyst: int = DEFAULT_SCOUT_BUDGET_PER_ANALYST
    scout_search_budget: int = DEFAULT_SCOUT_SEARCH_BUDGET
    model_overrides: dict[tuple[TaskTier, RoleClass], str] = field(default_factory=dict)
    skip_landscape: bool = False

    @staticmethod
    def from_payload(payload: dict[str, Any] | None) -> RunConfig:
        """Build a RunConfig from the API's optional `config` payload.

        Payload shape (all fields optional):
          {
            "analyst_budget": int,
            "scout_budget_per_analyst": int,
            "scout_search_budget": int,
            "model_overrides": {
              "MID": {"generative": "anthropic/claude-opus-4-7"},
              "HIGH": {"judgment": "openai/gpt-5.5"},
              ...
            }
          }

        Invalid values are clamped to the slider ranges; unknown model
        strings pass through as-is (the router will reject them at
        first use).
        """
        if not payload:
            return RunConfig()

        def _clamp(val: Any, default: int, lo: int, hi: int) -> int:
            try:
                n = int(val)
            except (TypeError, ValueError):
                return default
            return max(lo, min(hi, n))

        ab = _clamp(payload.get("analyst_budget"), DEFAULT_ANALYST_BUDGET, *ANALYST_BUDGET_RANGE)
        sb = _clamp(
            payload.get("scout_budget_per_analyst"),
            DEFAULT_SCOUT_BUDGET_PER_ANALYST,
            *SCOUT_BUDGET_RANGE,
        )
        ssb = _clamp(
            payload.get("scout_search_budget"),
            DEFAULT_SCOUT_SEARCH_BUDGET,
            *SCOUT_SEARCH_BUDGET_RANGE,
        )

        overrides: dict[tuple[TaskTier, RoleClass], str] = {}
        raw_overrides = payload.get("model_overrides") or {}
        if isinstance(raw_overrides, dict):
            for tier_key, roles in raw_overrides.items():
                if not isinstance(roles, dict):
                    continue
                try:
                    tier = TaskTier(tier_key)
                except ValueError:
                    continue
                for role_key, model_id in roles.items():
                    try:
                        role = RoleClass(role_key)
                    except ValueError:
                        continue
                    if isinstance(model_id, str) and model_id.strip():
                        overrides[(tier, role)] = model_id.strip()

        skip_landscape = bool(payload.get("skip_landscape", False))

        return RunConfig(
            analyst_budget=ab,
            scout_budget_per_analyst=sb,
            scout_search_budget=ssb,
            model_overrides=overrides,
            skip_landscape=skip_landscape,
        )

    def apply_to_routing(self, routing: RoutingConfig) -> RoutingConfig:
        """Return a new RoutingConfig with model_overrides applied.

        Non-overridden (tier, role) slots pass through unchanged. The
        result keeps the same `name` and `description` so log lines
        reading `routing.name` stay stable.
        """
        if not self.model_overrides:
            return routing

        new_tiers: dict[TaskTier, TierRouting] = {}
        for tier, tier_routing in routing.tiers.items():
            updates: dict[str, str] = {}
            for role in RoleClass:
                override = self.model_overrides.get((tier, role))
                if override is not None:
                    updates[role.value] = override
            new_tiers[tier] = tier_routing.model_copy(update=updates) if updates else tier_routing
        return routing.model_copy(update={"tiers": new_tiers})


def defaults_payload(routing: RoutingConfig) -> dict[str, Any]:
    """Snapshot defaults + slider ranges + catalog + current routing.

    Served as JSON by `GET /api/config/defaults`. `routing_defaults`
    mirrors the server's loaded routing YAML so the UI can preselect
    the actual default model in each dropdown instead of a blank
    placeholder. Keeping this shape adjacent to the dataclass means the
    UI can never drift from the backend's accepted values.
    """
    routing_defaults: dict[str, dict[str, str]] = {}
    for tier, tier_routing in routing.tiers.items():
        routing_defaults[tier.value] = {
            "generative": tier_routing.generative,
            "judgment": tier_routing.judgment,
            "cheap_deterministic": tier_routing.cheap_deterministic,
        }
    return {
        "budgets": {
            "analyst_budget": {
                "default": DEFAULT_ANALYST_BUDGET,
                "min": ANALYST_BUDGET_RANGE[0],
                "max": ANALYST_BUDGET_RANGE[1],
            },
            "scout_budget_per_analyst": {
                "default": DEFAULT_SCOUT_BUDGET_PER_ANALYST,
                "min": SCOUT_BUDGET_RANGE[0],
                "max": SCOUT_BUDGET_RANGE[1],
            },
            "scout_search_budget": {
                "default": DEFAULT_SCOUT_SEARCH_BUDGET,
                "min": SCOUT_SEARCH_BUDGET_RANGE[0],
                "max": SCOUT_SEARCH_BUDGET_RANGE[1],
            },
        },
        "model_catalog": {role.value: list(models) for role, models in MODEL_CATALOG.items()},
        "routing_defaults": routing_defaults,
        "toggles": {
            "skip_landscape": {
                "default": False,
                "label": "Skip landscape step",
                "help": (
                    "Bypass the landscape agent. The researcher starts with no brief "
                    "and no pre-scouted sources. Use to A/B whether landscape helps."
                ),
            },
        },
    }
