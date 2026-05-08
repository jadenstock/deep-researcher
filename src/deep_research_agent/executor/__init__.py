"""Agent executor + role-to-model routing.

AgentExecutor implements the scheduler's Executor protocol by dispatching
task types to per-type handlers. Routing resolves `(role, tier)` to a
model identifier; the cross-family invariant is checked at model-selection
time, not by prompt discipline.
"""

from .executor import AgentExecutor, HandlerContext, HandlerFn, UnhandledTaskType
from .handlers import register_v0_handlers
from .routing import CrossFamilyViolation, select_model

__all__ = [
    "AgentExecutor",
    "CrossFamilyViolation",
    "HandlerContext",
    "HandlerFn",
    "UnhandledTaskType",
    "register_v0_handlers",
    "select_model",
]
