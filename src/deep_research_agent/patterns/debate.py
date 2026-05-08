"""debate pattern — two adversarial researchers + a judge.

Where multi_perspective spreads claim extraction across three
complementary framings (neutral/skeptic/advocate), debate forces a
direct confrontation: one analyzer argues the affirmative, one argues
the negative, and the synthesizer is replaced with a judge prompt that
evaluates which side has the stronger evidence.

Triggered by the replanner on strongly contested questions where
multi_perspective's synthesis still shows surviving dissent that the
framings were talking past each other on.
"""

from __future__ import annotations

from .multi_perspective import Perspective

DEBATE_FRAMINGS: tuple[Perspective, ...] = (
    Perspective(
        name="affirmative",
        prompt_suffix=(
            "You are arguing the AFFIRMATIVE position on the question. "
            "Extract claims from this source that support YES / true / the "
            "stronger case for the proposition the question implies. Do not "
            "invent evidence — still quote verbatim — but select the quotes "
            "that make the strongest affirmative case. If the source is "
            "entirely against the affirmative, extract zero claims and set "
            "off_topic=False (the source is on-topic but not useful to you)."
        ),
    ),
    Perspective(
        name="negative",
        prompt_suffix=(
            "You are arguing the NEGATIVE position on the question. "
            "Extract claims from this source that support NO / false / the "
            "stronger case against the proposition the question implies. Do "
            "not invent evidence — still quote verbatim — but select the "
            "quotes that make the strongest negative case. If the source "
            "is entirely for the affirmative, extract zero claims."
        ),
    ),
)
