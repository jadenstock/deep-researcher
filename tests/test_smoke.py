"""Smoke test — harness runs, fakes import, asyncio mode works."""

from __future__ import annotations

import pytest

from tests.fakes.llm import FakeLLMRunner, ScriptMissing


async def test_fake_runner_requires_script() -> None:
    runner = FakeLLMRunner()
    with pytest.raises(ScriptMissing):
        await runner.run(
            script_key="unseen",
            role="generative",
            tier="MID",
            output_type=str,
            system_prompt="",
            user_prompt="",
        )


async def test_fake_runner_returns_scripted_response() -> None:
    runner = FakeLLMRunner()
    runner.script("ping", {"ok": True})
    got = await runner.run(
        script_key="ping",
        role="generative",
        tier="MID",
        output_type=dict,
        system_prompt="",
        user_prompt="ping?",
    )
    assert got == {"ok": True}
    assert len(runner.calls) == 1
    assert runner.calls[0].user_prompt == "ping?"
