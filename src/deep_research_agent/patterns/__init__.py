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
