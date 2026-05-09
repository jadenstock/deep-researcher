"""AgentExecutor constructs a PydanticAIRunner and exposes it on
HandlerContext as ctx.llm."""

from __future__ import annotations

from deep_research_agent.executor.executor import AgentExecutor
from deep_research_agent.executor.llm import PydanticAIRunner


async def test_agent_executor_exposes_llm_runner(routing_config_basic, local_config) -> None:
    ex = AgentExecutor(routing=routing_config_basic, local=local_config)
    assert isinstance(ex.llm, PydanticAIRunner)
