from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from deep_research_agent.pricing import ModelPrice
from deep_research_agent.progress import ProgressPublisher, read_status
from deep_research_agent.schemas.enums import AgentType, RoleClass, TaskTier

PRICES = {"claude-haiku-5-5": ModelPrice(1e-6, 5e-6, 1e-7)}


def _publisher(run_dir: Path) -> ProgressPublisher:
    return ProgressPublisher(
        run_dir, run_id=run_dir.name, query="q", analyst_budget=4, prices=PRICES
    )


def _usage(pub: ProgressPublisher, *, final: bool, input_tokens: int) -> None:
    common = {
        "agent_id": "ana-1",
        "agent_type": AgentType.ANALYST,
        "model_id": "anthropic/claude-haiku-5-5",
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }
    if final:
        pub.on_token_usage(**common, cache_write_tokens=0)
    else:
        pub.on_usage_progress(**common)


def test_running_and_final_usage_for_one_agent_are_not_double_counted(tmp_path: Path) -> None:
    pub = _publisher(tmp_path / "run-a")
    pub.on_agent_start(
        agent_id="ana-1",
        agent_type=AgentType.ANALYST,
        goal="g",
        tier=TaskTier.MID,
        role=RoleClass.GENERATIVE,
        model_id="anthropic/claude-haiku-5-5",
    )

    _usage(pub, final=False, input_tokens=100_000)
    _usage(pub, final=False, input_tokens=300_000)
    _usage(pub, final=True, input_tokens=400_000)
    pub.finish(ok=True)

    written = json.loads((tmp_path / "run-a" / "progress.json").read_text())
    assert written["tokens"]["input"] == 400_000
    assert written["cost_usd"] == pytest.approx(0.4)
    assert written["analysts"] == {"dispatched": 1, "budget": 4}
    assert written["phase"] == "finished"


def test_run_summary_marks_run_over_even_if_progress_looks_live(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-b"
    run_dir.mkdir()
    (run_dir / "progress.json").write_text(json.dumps({"finished": False, "pid": os.getpid()}))
    (run_dir / "run_summary.json").write_text(json.dumps({"finished": True}))
    (run_dir / "report.json").write_text("{}")

    assert read_status(run_dir).state == "finished"


def test_unfinished_run_whose_process_is_gone_is_crashed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-c"
    run_dir.mkdir()
    (run_dir / "progress.json").write_text(json.dumps({"finished": False, "pid": 2**22 + 12345}))

    assert read_status(run_dir).state == "crashed"


def test_unfinished_run_with_live_process_is_running(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-d"
    run_dir.mkdir()
    (run_dir / "progress.json").write_text(json.dumps({"finished": False, "pid": os.getpid()}))

    assert read_status(run_dir).state == "running"


def test_run_dir_without_progress_or_summary_is_failed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-e"
    run_dir.mkdir()

    assert read_status(run_dir).state == "failed"
