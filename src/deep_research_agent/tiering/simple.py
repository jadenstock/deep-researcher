"""v0 source tiering: static reject list + domain heuristics.

Replaced in v2 by an LLM tier classifier with inspectable rationale
(ADR 0003). This function exists only so v0 runs have tier-tagged
source_notes; it does not try to be accurate.
"""

from __future__ import annotations

from ..schemas.enums import Tier

REJECT_DOMAINS: frozenset[str] = frozenset(
    {
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "reddit.com",
        "tiktok.com",
        "youtube.com",
        "pinterest.com",
        "quora.com",
    }
)

ACADEMIC_OR_GOV_MARKERS: tuple[str, ...] = (
    "arxiv.org",
    "nature.com",
    "science.org",
    "pnas.org",
    "nejm.org",
    "acm.org",
    "ieee.org",
    "springer.com",
    "wiley.com",
    ".edu/",
    ".edu ",
    ".gov/",
    ".gov ",
)


def quick_tier(url: str) -> tuple[Tier, str]:
    """Rough tier from URL alone. Returns (tier, rationale).

    Tier 5 for reject-list domains; Tier 2 for known academic/gov
    markers; Tier 3 for everything else. Deliberately conservative:
    v0 should not promote rigor it hasn't verified.
    """
    url_l = url.lower()
    for d in REJECT_DOMAINS:
        if d in url_l:
            return Tier.TIER_5, f"reject list match: {d}"
    for marker in ACADEMIC_OR_GOV_MARKERS:
        if marker in url_l:
            return Tier.TIER_2, f"academic/government domain marker: {marker.strip()}"
    return Tier.TIER_3, "generic web source (v0 default tier)"
