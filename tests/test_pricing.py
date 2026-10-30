from __future__ import annotations

import pytest
from deep_research_agent.pricing import cost_usd, parse_model_info, tracker_cost_usd

MODEL_INFO = [
    {
        "model_name": "claude-haiku-5-5",
        "model_info": {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    },
    {
        "model_name": "gpt-6-luna",
        "model_info": {"input_cost_per_token": 2e-6, "output_cost_per_token": 8e-6},
    },
    {"model_name": "embedding-only", "model_info": {"input_cost_per_token": 1e-8}},
]


def test_cached_input_is_billed_at_cache_rate_and_ids_are_normalized() -> None:
    prices = parse_model_info(MODEL_INFO)

    cost = cost_usd(
        prices,
        "anthropic/claude-haiku-5-5",
        input_tokens=1_000_000,
        output_tokens=10_000,
        cache_read_tokens=800_000,
    )

    # 200k uncached at $1/M + 800k cached at $0.1/M + 10k output at $5/M
    assert cost == pytest.approx(0.2 + 0.08 + 0.05)


def test_effort_suffix_is_ignored_and_missing_cache_price_falls_back_to_input() -> None:
    prices = parse_model_info(MODEL_INFO)

    cost = cost_usd(
        prices,
        "openai/gpt-6-luna:high",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=500_000,
    )

    assert cost == pytest.approx(2.0)


def test_total_is_unknown_when_any_used_model_has_no_price() -> None:
    prices = parse_model_info(MODEL_INFO)
    usage = {"input_tokens": 1000, "output_tokens": 10, "cache_read_tokens": 0}

    cost = tracker_cost_usd(
        prices,
        {"per_model": {"anthropic/claude-haiku-5-5": usage, "openai/not-on-router": usage}},
    )

    assert cost["total"] is None
    assert cost["per_model"]["openai/not-on-router"] is None
    assert cost["per_model"]["anthropic/claude-haiku-5-5"] is not None
