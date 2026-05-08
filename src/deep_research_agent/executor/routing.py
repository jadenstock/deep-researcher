"""Resolve `(role, tier)` → model_id via the run's RoutingConfig.

Enforces the ADR 0008 cross-family invariant at model-selection time:
for task types listed in `routing.cross_family_invariant.applies_to`,
the resolved model's family must differ from the caller-supplied
`forbidden_family`. When it doesn't, raises CrossFamilyViolation so the
caller can either pick a different tier, route manually, or abandon
the task — breaking the invariant silently defeats ADR 0008's purpose.
"""

from __future__ import annotations

from ..config import RoutingConfig
from ..schemas.enums import RoleClass, TaskTier, TaskType


class CrossFamilyViolation(RuntimeError):
    """Routing would break the cross-family invariant for this task."""


def select_model(
    routing: RoutingConfig,
    role: RoleClass,
    tier: TaskTier,
    task_type: TaskType,
    forbidden_family: str | None = None,
) -> str:
    """Resolve a model identifier for this task.

    If task_type is under the cross-family invariant AND forbidden_family
    is provided, verify the resolved model comes from a different family.
    """
    model_id = routing.model_id_for(role, tier)
    inv = routing.cross_family_invariant
    if inv.enabled and task_type in inv.applies_to and forbidden_family is not None:
        resolved = routing.family_of(model_id)
        if resolved == forbidden_family:
            raise CrossFamilyViolation(
                f"{task_type.value} resolves to family {resolved!r} "
                f"but must differ from {forbidden_family!r} (ADR 0008)."
            )
    return model_id
