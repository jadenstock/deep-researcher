"""Agent executor + role-to-model routing.

One PydanticAI agent per task type. The executor resolves `(role, tier)` to
a model via the run's routing config, enforces the cross-family invariant
(VERIFY_CLAIM's model family must differ from the ANALYZE_SOURCE family
that produced the claim), forks a fresh context, runs the agent, and
returns its structured output + any note mutations + any spawned sub-tasks.
"""
