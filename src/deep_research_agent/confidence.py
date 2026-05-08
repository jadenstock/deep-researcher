"""Tier-weighted confidence formula + language ladder (TDD §5.7).

Confidence is computed from a set of supporting sources plus refuting
sources, a triangulation score, and a peer-review majority check. The
preliminary-anchor cap (0.80) is load-bearing: even if the LLM tier
classifier over-tiers a rigorous-but-not-peer-reviewed source, confidence
cannot cross into the "High" band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .schemas.enums import Tier

ConfidenceBand = Literal["High", "Moderate", "Low"]

TIER_WEIGHT: dict[Tier, float] = {
    Tier.TIER_1: 0.90,
    Tier.TIER_2: 0.75,
    Tier.TIER_3: 0.55,
    Tier.TIER_4: 0.30,
    # Tier.TIER_5 sources are never loaded into the corpus; no weight defined.
}

PRELIMINARY_CAP = 0.80


@dataclass(frozen=True)
class SourceEvidence:
    tier: Tier
    peer_reviewed: bool
    citation_count: int


@dataclass(frozen=True)
class ConfidenceInput:
    supporting: list[SourceEvidence]
    refuting: list[SourceEvidence]
    triangulation_score: float  # 0..1, see §5.16

    @property
    def primarily_preliminary(self) -> bool:
        if not self.supporting:
            return True
        n_prelim = sum(1 for s in self.supporting if not s.peer_reviewed)
        return n_prelim * 2 > len(self.supporting)


@dataclass(frozen=True)
class ConfidenceResult:
    value: float  # 0..1
    band: ConfidenceBand
    primarily_preliminary: bool
    capped: bool  # True if preliminary-anchor cap was applied


def compute_confidence(ci: ConfidenceInput) -> ConfidenceResult:
    if not ci.supporting:
        return ConfidenceResult(value=0.0, band="Low", primarily_preliminary=True, capped=False)

    base = max(TIER_WEIGHT[s.tier] for s in ci.supporting)
    agreement_bonus = min(0.10 * (len(ci.supporting) - 1), 0.30)
    max_cites = max(s.citation_count for s in ci.supporting)
    citation_signal = min(math.log10(max_cites + 1) / 5.0, 0.10)
    contradiction_penalty = 0.20 if ci.refuting else 0.0
    triangulation_bonus = ci.triangulation_score * 0.10

    raw = base + agreement_bonus + citation_signal + triangulation_bonus - contradiction_penalty
    raw = max(0.0, min(1.0, raw))

    capped = False
    if ci.primarily_preliminary and raw > PRELIMINARY_CAP:
        raw = PRELIMINARY_CAP
        capped = True

    return ConfidenceResult(
        value=raw,
        band=band_of(raw),
        primarily_preliminary=ci.primarily_preliminary,
        capped=capped,
    )


def band_of(value: float) -> ConfidenceBand:
    """Map a numeric confidence to the standardized three-band label."""
    if value >= 0.80:
        return "High"
    if value >= 0.55:
        return "Moderate"
    return "Low"


# Language ladder — the full render is produced by WRITE_REPORT; these are the
# canonical qualifiers per band. Multiple options allow light stylistic
# variation without drifting into uncalibrated language.
BAND_QUALIFIERS: dict[ConfidenceBand, tuple[str, ...]] = {
    "High": ("almost certainly", "highly likely", "we assess with high confidence"),
    "Moderate": ("likely", "probably", "we assess"),
    "Low": ("possible", "unlikely", "remote"),
}


def render_confidence_tag(result: ConfidenceResult) -> str:
    """One-line confidence caveat suitable for appending after a claim."""
    tag = f"*({result.band} confidence, {result.value:.2f}"
    if result.primarily_preliminary:
        tag += "; primarily preliminary evidence"
    tag += ".)*"
    return tag
