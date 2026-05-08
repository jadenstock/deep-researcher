"""Orchestration patterns.

Each pattern is a pure function that takes a sub-question + context and
emits a list of Task entries with typed dependencies — no execution side
effects. The scheduler dispatches what the pattern emits.

Patterns:
    single_researcher   — scanner → analyzer → question_synthesize (default)
    maker_checker       — verify claims on the judgment family
    multi_perspective   — N parallel single_researcher runs + merge
    debate              — two ADVERSARIAL_CRITIQUE tasks + adjudication
    ach                 — per-hypothesis consistency batching + adjudication
"""

from .maker_checker import (
    MAX_CLAIMS_PER_RUN,
    MAX_CLAIMS_PER_SYNTHESIS,
    emit_verify_claim,
    select_claims_to_verify,
)
from .single_researcher import emit_decompose, emit_question_synthesize, emit_write_report

__all__ = [
    "MAX_CLAIMS_PER_RUN",
    "MAX_CLAIMS_PER_SYNTHESIS",
    "emit_decompose",
    "emit_question_synthesize",
    "emit_verify_claim",
    "emit_write_report",
    "select_claims_to_verify",
]
