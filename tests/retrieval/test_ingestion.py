"""ingest_source pipeline: short content path.

Short content (< 8K tokens) should return IngestionResult with the full
markdown in .content and structured_content=None."""

from __future__ import annotations

from deep_research_agent.retrieval.fetch import FetchResult
from deep_research_agent.retrieval.ingestion import IngestionResult, ingest_source
from deep_research_agent.schemas.enums import Tier
from tests.fakes.retrieval import FakeFetcher, FakeTierClassifier


async def test_short_content_returns_full_markdown_and_no_structure() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()

    fetcher.script(
        "https://example.com/post",
        FetchResult(
            url="https://example.com/post",
            final_url="https://example.com/post",
            status_code=200,
            content_type="text/html",
            title="A short post",
            markdown="# A short post\n\nJust a paragraph.",
            byte_length=100,
        ),
    )
    classifier.script(
        "https://example.com/post",
        tier=Tier.TIER_3,
        rationale="blog post",
        confidence=0.7,
        peer_reviewed=False,
    )

    result: IngestionResult = await ingest_source(
        url="https://example.com/post",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "ok"
    assert result.content == "# A short post\n\nJust a paragraph."
    assert result.structured_content is None
    assert result.tier == Tier.TIER_3
    assert result.peer_reviewed is False
    assert result.title == "A short post"
