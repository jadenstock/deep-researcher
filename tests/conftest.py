"""Project-wide test fixtures. Keep this file small — domain-specific
fixtures belong in nearer conftest.py files."""

from __future__ import annotations

import pytest

from deep_research_agent.config import LLMEndpoint, LocalConfig


@pytest.fixture
def local_config() -> LocalConfig:
    """A LocalConfig instance safe for tests — never hits a real endpoint."""
    return LocalConfig(
        llm=LLMEndpoint(
            api_base_url="http://test.invalid/v1",
            api_key="test-key-not-used",
        ),
    )
