"""multi_perspective pattern — N analyzers with distinct framings.

Instead of one analyzer reading each source with a neutral framing, the
multi_perspective pattern runs the analyzer N times with different
framings (ADR 0004-adjacent: distinct epistemic stances stress-test
the source). Claims from each framing are merged and tagged so the
synthesizer can see where the framings agree, disagree, or surface
different facets.

Triggered by the replanner via EscalatePattern on contested
sub-questions where single_researcher's surviving_dissent shows the
positions haven't been adequately engaged.
"""

from __future__ import annotations

from dataclasses import dataclass

# Perspective definitions. Three is the practical minimum — you want
# coverage of the obvious "charitable / critical / neutral" triad.
# More framings make the cost super-linear; keep this list short.


@dataclass(frozen=True)
class Perspective:
    name: str
    prompt_suffix: str


PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective(
        name="neutral",
        prompt_suffix=(
            "Take a neutral analytical stance. Extract claims the source "
            "actually makes without editorializing. This is the baseline view."
        ),
    ),
    Perspective(
        name="skeptic",
        prompt_suffix=(
            "Take a skeptical stance. Ask: what is this source failing to "
            "justify? Where is its reasoning thin? Extract the claims the "
            "source makes but include quotes that reveal unjustified leaps "
            "or missing evidence. Do not invent contradictions the source "
            "does not raise — still quote verbatim."
        ),
    ),
    Perspective(
        name="advocate",
        prompt_suffix=(
            "Take a steelmanning stance. Extract the strongest version of "
            "the source's claims — what does it establish most convincingly? "
            "Quote the passages that are most load-bearing for its case."
        ),
    ),
)


def get_perspective(name: str) -> Perspective | None:
    return next((p for p in PERSPECTIVES if p.name == name), None)
