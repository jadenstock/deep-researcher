"""LLMRunner contract: selects model via routing, tracks tokens,
returns typed output wrapped in LLMResult."""

from __future__ import annotations

from deep_research_agent.executor.llm import LLMResult, PydanticAIRunner
from pydantic import BaseModel

from deep_research_agent.schemas.enums import RoleClass, TaskTier


class _EchoOutput(BaseModel):
    echo: str


async def test_pydantic_ai_runner_resolves_model_from_routing(
    routing_config_basic, local_config, fake_pydantic_ai_agent
) -> None:
    """The runner resolves (role, tier) → model_id via routing config and
    hands that model_id to the constructed Agent."""
    runner = PydanticAIRunner(
        routing=routing_config_basic,
        local=local_config,
        tracker=None,
        agent_factory=fake_pydantic_ai_agent,
    )
    fake_pydantic_ai_agent.script_output(_EchoOutput(echo="hi"))

    result: LLMResult[_EchoOutput] = await runner.run(
        role=RoleClass.GENERATIVE,
        tier=TaskTier.MID,
        output_type=_EchoOutput,
        system_prompt="you echo",
        user_prompt="hi",
        task_type="TEST",
    )

    assert result.output.echo == "hi"
    assert fake_pydantic_ai_agent.last_model_id == routing_config_basic.model_id_for(
        RoleClass.GENERATIVE, TaskTier.MID
    )
