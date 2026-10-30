"""PydanticAI model factory.

Turn a routing-config model_id plus the local LLM endpoint into a
PydanticAI model object. All families route through the same
OpenAI-compatible endpoint (LiteLLM router); the model_id is sent
as-is - the router resolves it to the upstream provider.
"""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .config import LocalConfig, RoutingConfig

# Router (LiteLLM -> Anthropic) applies a low default cap when clients omit
# `max_tokens`, which truncated answer_question tool-call args mid-report and
# ran the agent through its retry budget. Set a ceiling large enough for a
# full final report with thinking headroom.
_DEFAULT_MAX_TOKENS = 16384

# pydantic-ai's default httpx client uses connect=5s, which is brittle against
# router blips - a single slow TCP handshake surfaces as ModelAPIError and
# unwinds the whole Researcher -> Analyst -> Scout stack. Read timeout stays
# at the pydantic-ai default (600s); openai SDK gets a slightly higher retry
# count so a transient connect failure doesn't exhaust the budget in ~15s.
_CONNECT_TIMEOUT_S = 30.0
_READ_TIMEOUT_S = 600.0
_MAX_RETRIES = 5

# Anthropic only caches prompts that carry `cache_control` markers, which
# pydantic-ai's OpenAI-compatible client never sends - so every Claude tool
# turn re-paid its full context. LiteLLM injects the markers for us: one on
# the system prompt and one on the trailing message, so the cached prefix
# advances with the agent loop. GPT models on the router cache automatically.
_ANTHROPIC_CACHE_POINTS = [
    {"location": "message", "role": "system"},
    {"location": "message", "index": -1},
]


def make_model(model_id: str, local: LocalConfig) -> OpenAIChatModel:
    """Build a PydanticAI model for the given routing model_id.

    Routing identifiers are `family/model` (e.g. "anthropic/claude-opus-5-5");
    the family prefix is a local convention for the cross-family invariant.
    The router expects the bare model name, so we strip before dispatch.
    An optional ':<effort>' suffix (e.g. "openai/gpt-6-luna:high") is sent
    as `reasoning_effort`.
    """
    settings = OpenAIChatModelSettings(max_tokens=_DEFAULT_MAX_TOKENS)
    if model_id.startswith("anthropic/"):
        settings["extra_body"] = {"cache_control_injection_points": _ANTHROPIC_CACHE_POINTS}
    effort = RoutingConfig.reasoning_effort(model_id)
    if effort:
        settings["openai_reasoning_effort"] = effort  # type: ignore[typeddict-item]
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
    )
    openai_client = AsyncOpenAI(
        base_url=local.llm.api_base_url,
        api_key=local.llm.api_key,
        http_client=http_client,
        max_retries=_MAX_RETRIES,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    return OpenAIChatModel(
        RoutingConfig.router_name(model_id),
        provider=provider,
        settings=settings,
    )
