"""PydanticAI model factory.

Turn a routing-config model_id plus the local LLM endpoint into a
PydanticAI model object. All families route through the same
OpenAI-compatible endpoint (LiteLLM router); the model_id is sent
as-is - the router resolves it to the upstream provider.
"""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config import LocalConfig, RoutingConfig


def make_model(model_id: str, local: LocalConfig) -> OpenAIChatModel:
    """Build a PydanticAI model for the given routing model_id.

    Routing identifiers are `family/model` (e.g. "anthropic/claude-opus-4-7");
    the family prefix is a local convention for the cross-family invariant.
    The router expects the bare model name, so we strip before dispatch.
    """
    provider = OpenAIProvider(
        base_url=local.llm.api_base_url,
        api_key=local.llm.api_key,
    )
    return OpenAIChatModel(RoutingConfig.router_name(model_id), provider=provider)
