"""Deterministic fake for the LLMRunner protocol.

Usage:
    runner = FakeLLMRunner()
    runner.script("tier_classify", TierClassifierOutput(
        tier=2, rationale="arXiv preprint", confidence=0.8, peer_reviewed=False
    ))
    result = await runner.run(script_key="tier_classify", ...)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ScriptMissing(KeyError):
    """No scripted response registered for this key."""


@dataclass
class RunnerCall:
    script_key: str
    role: str
    tier: str
    system_prompt: str
    user_prompt: str


@dataclass
class FakeLLMRunner:
    _responses: dict[str, Any] = field(default_factory=dict)
    _handlers: dict[str, Callable[[RunnerCall], Any]] = field(default_factory=dict)
    calls: list[RunnerCall] = field(default_factory=list)

    def script(self, key: str, response: Any) -> None:
        """Register a literal response for `key`."""
        self._responses[key] = response

    def script_fn(self, key: str, fn: Callable[[RunnerCall], Any]) -> None:
        """Register a callable that receives the call and returns the response.

        Use when the response must depend on the user_prompt (e.g., tier-
        classify a specific URL)."""
        self._handlers[key] = fn

    async def run(
        self,
        *,
        script_key: str,
        role: Any,
        tier: Any,
        output_type: type,
        system_prompt: str,
        user_prompt: str,
        task_type: str | None = None,
    ) -> Any:
        # output_type and task_type are accepted for signature compatibility
        # with the real LLMRunner; the fake doesn't exercise them.
        del output_type, task_type
        call = RunnerCall(
            script_key=script_key,
            role=str(role),
            tier=str(tier),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        self.calls.append(call)
        if script_key in self._handlers:
            return self._handlers[script_key](call)
        if script_key not in self._responses:
            raise ScriptMissing(
                f"No scripted response for key={script_key!r}. "
                f"Registered keys: {list(self._responses)}"
            )
        return self._responses[script_key]
