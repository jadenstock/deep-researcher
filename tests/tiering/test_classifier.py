"""Tests for classify_source_via_runner — the LLM-runner-backed path
for ADR-0003 tier classification."""

from __future__ import annotations

from deep_research_agent.schemas.enums import Tier
from deep_research_agent.tiering.classifier import (
    TierClassifierOutput,
    classify_source_via_runner,
)
from tests.fakes.llm import FakeLLMRunner


async def test_reject_list_short_circuits_to_tier_5() -> None:
    runner = FakeLLMRunner()  # no scripts — must not be called
    tier, rationale, _confidence, _peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="spam",
        url="https://pinterest.com/xyz",
        snippet="",
        content="",
    )
    assert tier == Tier.TIER_5
    assert "reject list" in rationale
    assert runner.calls == []  # no LLM call happened


async def test_classifier_calls_runner_with_cheap_deterministic_low() -> None:
    runner = FakeLLMRunner()
    runner.script(
        "tier_classify",
        TierClassifierOutput(
            tier=2,
            rationale="arXiv preprint with methodology",
            confidence=0.8,
            peer_reviewed=False,
        ),
    )
    tier, _rationale, _confidence, peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="Attention Is All You Need",
        url="https://arxiv.org/abs/1706.03762",
        snippet="We propose the Transformer...",
        content="# Abstract\nWe propose..." * 200,
    )
    assert tier == Tier.TIER_2
    assert peer_reviewed is False
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call.role == "RoleClass.CHEAP_DETERMINISTIC"
    assert call.tier == "TaskTier.LOW"


async def test_classifier_fallback_on_runner_exception() -> None:
    class _BoomRunner(FakeLLMRunner):
        async def run(self, **kwargs):
            raise RuntimeError("boom")

    runner = _BoomRunner()
    tier, _rationale, confidence, peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="x",
        url="https://example.com/article",
        snippet="",
        content="x" * 100,
    )
    assert tier == Tier.TIER_3
    assert confidence <= 0.3
    assert peer_reviewed is False
