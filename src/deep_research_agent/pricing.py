"""Per-token model prices from the LiteLLM router, and cost math.

The router's `/model/info` endpoint lists input / output / cache-read
prices per model. We fetch it once per run (best effort: a router that
doesn't expose it, or a network blip, just means costs are reported as
unknown) and price token totals with it.

Model ids in this codebase carry a family prefix and an optional
reasoning-effort suffix (`openai/gpt-6-luna:high`); prices are keyed by
the bare router name, so lookups go through `RoutingConfig.router_name`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import LocalConfig, RoutingConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    input_per_token: float
    output_per_token: float
    cache_read_per_token: float


ModelPrices = dict[str, ModelPrice]


async def fetch_router_prices(local: LocalConfig, timeout_s: float = 15.0) -> ModelPrices:
    """Fetch `{api_base_url}/model/info` and index prices by model name.

    Returns an empty dict on any failure; callers treat that as
    "cost unknown".
    """
    url = local.llm.api_base_url.rstrip("/") + "/model/info"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {local.llm.api_key}"})
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except Exception as exc:
        logger.warning("router price fetch failed url=%s err=%s", url, exc)
        return {}
    return parse_model_info(data)


def parse_model_info(data: list[dict[str, Any]]) -> ModelPrices:
    prices: ModelPrices = {}
    for entry in data:
        name = entry.get("model_name")
        info = entry.get("model_info") or {}
        inp = info.get("input_cost_per_token")
        out = info.get("output_cost_per_token")
        if not name or inp is None or out is None:
            continue
        cache = info.get("cache_read_input_token_cost")
        prices[name] = ModelPrice(
            input_per_token=float(inp),
            output_per_token=float(out),
            cache_read_per_token=float(cache if cache is not None else inp),
        )
    return prices


def cost_usd(
    prices: ModelPrices,
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
) -> float | None:
    """Price one model's token totals. `input_tokens` includes cached
    tokens (that's how pydantic-ai reports them); cached ones are billed
    at the cache-read rate. None when the model has no known price."""
    price = prices.get(RoutingConfig.router_name(model_id))
    if price is None:
        return None
    uncached = max(0, input_tokens - cache_read_tokens)
    return (
        uncached * price.input_per_token
        + cache_read_tokens * price.cache_read_per_token
        + output_tokens * price.output_per_token
    )


def tracker_cost_usd(prices: ModelPrices, tracker_dict: dict[str, Any]) -> dict[str, Any]:
    """Cost breakdown for a `TokenUsageTracker.to_dict()` payload.

    Returns `{"total": float | None, "per_model": {model_id: float | None}}`.
    The total is None if any model with usage has no known price, so a
    partial sum is never mistaken for the real figure.
    """
    per_model: dict[str, float | None] = {}
    for model_id, t in (tracker_dict.get("per_model") or {}).items():
        per_model[model_id] = cost_usd(
            prices,
            model_id,
            input_tokens=int(t.get("input_tokens", 0)),
            output_tokens=int(t.get("output_tokens", 0)),
            cache_read_tokens=int(t.get("cache_read_tokens", 0)),
        )
    known = [c for c in per_model.values() if c is not None]
    total = sum(known) if per_model and len(known) == len(per_model) else None
    return {"total": total, "per_model": per_model}
