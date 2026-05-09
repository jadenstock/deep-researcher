"""Project-wide test fixtures. Keep this file small — domain-specific
fixtures belong in nearer conftest.py files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from deep_research_agent.config import LLMEndpoint, LocalConfig, RoutingConfig, load_routing_config


@pytest.fixture
def local_config() -> LocalConfig:
    """A LocalConfig instance safe for tests — never hits a real endpoint."""
    return LocalConfig(
        llm=LLMEndpoint(
            api_base_url="http://test.invalid/v1",
            api_key="test-key-not-used",
        ),
    )


@pytest.fixture
def routing_config_basic() -> RoutingConfig:
    """A real RoutingConfig loaded from config/routing_diverse.yaml.

    Tests use the actual production routing shape rather than a hand-rolled
    minimal one — keeps fixtures honest about the RoutingConfig contract."""
    config_path = Path(__file__).parent.parent / "config" / "routing_diverse.yaml"
    return load_routing_config(config_path)


@dataclass
class _FakePydanticAIAgent:
    """Captures what was passed to Agent(...) and returns a scripted output.

    Dual-role object: called as a factory (stores model_id / system_prompt /
    output_type, returns itself), then its .run() method is called by the
    runner (returns a RunResult-shaped object with .output and .usage)."""

    last_model_id: str | None = None
    last_system_prompt: str | None = None
    last_output_type: type | None = None
    last_user_prompt: str | None = None
    _scripted_output: Any = None

    def script_output(self, output: Any) -> None:
        self._scripted_output = output

    def __call__(self, model_id: str, local: Any, output_type: type, system_prompt: str) -> Any:
        # Also captures `local` argument but we don't assert on it in tests.
        del local
        self.last_model_id = model_id
        self.last_output_type = output_type
        self.last_system_prompt = system_prompt
        return self

    async def run(self, user_prompt: str) -> Any:
        self.last_user_prompt = user_prompt
        return _FakeRunResult(output=self._scripted_output)


@dataclass
class _FakeRunResult:
    output: Any

    def usage(self) -> None:
        return None


@pytest.fixture
def fake_pydantic_ai_agent() -> _FakePydanticAIAgent:
    return _FakePydanticAIAgent()
