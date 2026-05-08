"""Routing config loader.

A routing config is one YAML file per policy. At run time, the executor
consults it to map `(role, tier)` → model ID. The cross-family invariant
(VERIFY_CLAIM model family ≠ ANALYZE_SOURCE model family) is enforced by
the executor at dispatch time, not by this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .schemas.enums import RoleClass, TaskTier, TaskType


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
        """Resolve a (role, tier) pair to the configured model identifier."""
        return getattr(self.tiers[tier], role.value)

    @staticmethod
    def family_of(model_id: str) -> str:
        """Family := provider prefix of a `provider:model` identifier."""
        return model_id.split(":", 1)[0] if ":" in model_id else model_id


def load_routing_config(path: Path | str) -> RoutingConfig:
    p = Path(path)
    with p.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return RoutingConfig.model_validate(data)
