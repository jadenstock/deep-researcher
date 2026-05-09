"""Source extraction pipeline (CONTEXT.md §68-78, ADR-0007).

Given a URL, produce an IngestionResult that a caller can turn into a
populated source_note. The pipeline is deterministic (no LLM) except for
tier classification, which is delegated to a TierClassifier protocol.

Stages:
    1. Fetch (HTML → trafilatura, PDF → MarkItDown) via Fetcher protocol.
    2. Short-circuit to a "failed" IngestionResult on connection errors
       or empty markdown (caller records Tier 5, state=FETCHED).
    3. Tier classify via TierClassifier protocol.
    4. Size route: short content → full markdown; long content →
       StructuredContent + truncated raw.
    5. Return IngestionResult.

The module owns composition only — fetch and structure logic stays in
their respective modules.

Callers inject Fetcher and TierClassifier; tests inject fakes. The
default production Fetcher wraps fetch_and_extract(); the default
production TierClassifier wraps classify_source_via_runner().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..schemas.enums import Tier
from ..schemas.source import StructuredContent
from .fetch import FetchResult, fetch_and_extract
from .structure import build_structured_content, is_long_source

# Cap markdown stored on the note — the full raw is kept in the fetch
# cache and can be re-read by load_source_section.
MAX_NOTE_CONTENT_CHARS = 40_000


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult | None: ...


class TierClassifier(Protocol):
    async def classify(
        self, *, title: str, url: str, snippet: str, content: str
    ) -> tuple[Tier, str, float, bool]: ...


@dataclass(frozen=True)
class IngestionResult:
    status: Literal["ok", "fetch_failed"]
    url: str
    final_url: str
    title: str | None
    content: str  # markdown truncated to MAX_NOTE_CONTENT_CHARS; empty on failure
    structured_content: StructuredContent | None  # populated iff long source
    tier: Tier
    tier_rationale: str
    classifier_confidence: float
    peer_reviewed: bool


class _RealFetcher:
    async def fetch(self, url: str) -> FetchResult | None:
        return await fetch_and_extract(url)


def default_fetcher() -> Fetcher:
    return _RealFetcher()


async def ingest_source(
    *,
    url: str,
    snippet: str,
    fetcher: Fetcher,
    tier_classifier: TierClassifier,
) -> IngestionResult:
    """Run the source extraction pipeline for one URL.

    Returns an IngestionResult for every input — even failures. Callers
    never see raw fetch exceptions; they translate an IngestionResult
    into a NoteMutation directly."""
    fetch = await fetcher.fetch(url)
    if fetch is None or not fetch.markdown:
        return IngestionResult(
            status="fetch_failed",
            url=url,
            final_url=url,
            title=None,
            content="",
            structured_content=None,
            tier=Tier.TIER_5,
            tier_rationale="fetch failed (empty or blocked)",
            classifier_confidence=1.0,
            peer_reviewed=False,
        )

    title = fetch.title or url
    tier, rationale, confidence, peer_reviewed = await tier_classifier.classify(
        title=title, url=url, snippet=snippet, content=fetch.markdown
    )

    structured: StructuredContent | None = None
    if is_long_source(fetch.markdown):
        structured = build_structured_content(title, fetch.markdown)

    return IngestionResult(
        status="ok",
        url=url,
        final_url=fetch.final_url,
        title=fetch.title,
        content=fetch.markdown[:MAX_NOTE_CONTENT_CHARS],
        structured_content=structured,
        tier=tier,
        tier_rationale=rationale,
        classifier_confidence=confidence,
        peer_reviewed=peer_reviewed,
    )
