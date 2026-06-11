from __future__ import annotations

from deep_research_agent.server.report_filename import (
    fallback_report_filename,
    report_excerpt,
    sanitize_report_filename,
)


def test_sanitize_report_filename_normalizes_model_output() -> None:
    assert (
        sanitize_report_filename(' "LLM Calibration & Risk: 2026.md" ')
        == "llm-calibration-and-risk-2026.md"
    )


def test_sanitize_report_filename_falls_back_when_empty() -> None:
    assert sanitize_report_filename("!!!", fallback="fallback-title") == "fallback-title.md"


def test_fallback_report_filename_uses_query_then_run_id() -> None:
    assert (
        fallback_report_filename(
            "Confidence elicitation without logprobs",
            "20260611T000000-abcd1234",
        )
        == "confidence-elicitation-without-logprobs.md"
    )
    assert fallback_report_filename("", "20260611T000000-abcd1234") == "20260611T000000-abcd1234.md"


def test_report_excerpt_uses_top_slice() -> None:
    assert report_excerpt("ABCDE", max_chars=3) == "ABC"
