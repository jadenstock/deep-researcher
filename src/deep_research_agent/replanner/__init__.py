"""Bounded replanner (v3).

Runs periodically (default: every 10 task completions). Emits task-graph
mutations under a per-cycle budget (default: 3). Uses Round 4/5 framing:
premortem + metacognitive saturation check.

Termination is NOT a replanner prerogative — that requires the separate
deterministic CHECK_TERMINATION_READY audit (v4).
"""

from .outputs import (
    AbandonSubQuestion,
    EscalatePattern,
    NoOp,
    ReplanAction,
    ReplanDecision,
    SpawnSubQuestion,
)
from .replanner import DEFAULT_BUDGET, DEFAULT_CADENCE, ReplannerFailed, run_replanner

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_CADENCE",
    "AbandonSubQuestion",
    "EscalatePattern",
    "NoOp",
    "ReplanAction",
    "ReplanDecision",
    "ReplannerFailed",
    "SpawnSubQuestion",
    "run_replanner",
]
