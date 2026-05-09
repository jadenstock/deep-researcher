"""Query reformulation strategies for SCOUT_SOURCES.

Each strategy turns a topic or question into one or more search queries
that will surface a distinct slice of the corpus. Running multiple
strategies per scout task is how the pipeline achieves coverage breadth
— a single query hits Brave's top ~10 SEO-optimized pages; a bundle of
reformulated queries reaches contrarian takes, technical deep-dives,
recent preprints, and venue-specific material that a single query
misses.

All strategies take a `ScoutingConfig` so per-bundle caps
(`direct_max_hits`, `contrarian_n_reformulations`, etc.) are tunable
from `config/pipeline.yaml` without code changes. Functions return
`ScoutQuery` lists; callers dispatch them to Brave.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import ScoutingConfig


@dataclass(frozen=True)
class ScoutQuery:
    """One reformulated query with its strategy label.

    `strategy` is recorded on the resulting source_note as
    `scout_strategy` for post-hoc coverage analysis. `max_hits` caps the
    per-query fan-out.
    """

    query: str
    strategy: str
    max_hits: int = 5


def direct_queries(topic: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """Baseline: topic as-is. Always included."""
    return [ScoutQuery(query=topic, strategy="direct", max_hits=cfg.direct_max_hits)]


_CONTRARIAN_FORMS = (
    "criticism of {topic}",
    "limitations of {topic}",
    "problems with {topic}",
)


def contrarian_queries(topic: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """Surface pushback. Uses the first N reformulations (configurable)."""
    n = max(0, min(cfg.contrarian_n_reformulations, len(_CONTRARIAN_FORMS)))
    return [
        ScoutQuery(
            query=form.format(topic=topic),
            strategy="contrarian",
            max_hits=cfg.contrarian_max_hits,
        )
        for form in _CONTRARIAN_FORMS[:n]
    ]


def time_bounded_queries(
    topic: str, cfg: ScoutingConfig, months_back: int = 18
) -> list[ScoutQuery]:
    """Bias toward recent work. Uses Brave's `after:YYYY` filter when
    possible — cleaner than embedding year lists in the query text.
    """
    now = datetime.now(UTC)
    # Use after:YYYY — this is an actual operator Brave honors, unlike
    # the earlier "(2025 OR 2024)" form which treated the years as query
    # terms and broke ranking.
    cutoff_year = now.year - (months_back // 12)
    return [
        ScoutQuery(
            query=f"{topic} after:{cutoff_year}",
            strategy="time_bounded",
            max_hits=cfg.time_bounded_max_hits,
        )
    ]


def venue_queries(topic: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """Primary-source venues. One query per venue so results dedupe
    cleanly by URL.
    """
    return [
        ScoutQuery(
            query=f"{topic} site:{domain}",
            strategy=f"venue:{domain}",
            max_hits=max_hits,
        )
        for domain, max_hits in cfg.venue_queries
    ]


def question_focused_queries(question: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """For a specific sub-question: direct + evidence + review bundle."""
    return [
        ScoutQuery(
            query=question,
            strategy="question_direct",
            max_hits=cfg.question_direct_max_hits,
        ),
        ScoutQuery(
            query=f"evidence on {question}",
            strategy="question_evidence",
            max_hits=cfg.question_evidence_max_hits,
        ),
        ScoutQuery(
            query=f"review paper {question}",
            strategy="question_review",
            max_hits=cfg.question_review_max_hits,
        ),
    ]


def landscape_seed_queries(topic: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """Broad topical coverage for the initial landscape seed. Bundles
    direct, contrarian, time-bounded, and venue strategies.
    """
    return [
        *direct_queries(topic, cfg),
        *contrarian_queries(topic, cfg),
        *time_bounded_queries(topic, cfg),
        *venue_queries(topic, cfg),
    ]


def verify_seed_queries(topic: str, cfg: ScoutingConfig) -> list[ScoutQuery]:
    """Minimal bundle used when VERIFY_CLAIM spawns a SCOUT_SOURCES for
    corroboration — one direct query, higher max_hits than per-query
    defaults so the verifier gets enough candidates.
    """
    return [
        ScoutQuery(
            query=topic,
            strategy="verify_direct",
            max_hits=cfg.verify_seed_max_hits,
        )
    ]
