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


async def test_long_content_builds_structured_content() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()

    # Build a ~10K-token (~40K chars) markdown with real section structure
    # so build_structured_content has something to chew.
    long_md_parts = ["# Long paper\n\nAbstract paragraph here.\n\n"]
    for i in range(5):
        long_md_parts.append(f"## Section {i}\n\n" + ("filler " * 1200) + "\n\n")
    long_md = "".join(long_md_parts)

    fetcher.script(
        "https://arxiv.org/abs/9999.99999",
        FetchResult(
            url="https://arxiv.org/abs/9999.99999",
            final_url="https://arxiv.org/abs/9999.99999",
            status_code=200,
            content_type="text/html",
            title="Long paper",
            markdown=long_md,
            byte_length=len(long_md),
        ),
    )
    classifier.script(
        "https://arxiv.org/abs/9999.99999",
        tier=Tier.TIER_2,
        rationale="arXiv preprint",
        confidence=0.85,
        peer_reviewed=False,
    )

    result = await ingest_source(
        url="https://arxiv.org/abs/9999.99999",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "ok"
    assert result.structured_content is not None
    assert result.structured_content.abstract is not None
    assert len(result.structured_content.section_headers) >= 5
    # Raw markdown also stored, truncated
    assert len(result.content) <= 40_000


async def test_fetch_failure_returns_tier_5_result() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()  # must not be called
    fetcher.script("https://gone.example.com/", None)

    result = await ingest_source(
        url="https://gone.example.com/",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "fetch_failed"
    assert result.tier == Tier.TIER_5
    assert result.content == ""
    assert classifier.calls == []


async def test_empty_markdown_treated_as_fetch_failure() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()
    fetcher.script(
        "https://paywall.example.com/",
        FetchResult(
            url="https://paywall.example.com/",
            final_url="https://paywall.example.com/",
            status_code=200,
            content_type="text/html",
            title=None,
            markdown=None,
            byte_length=1000,
        ),
    )
    result = await ingest_source(
        url="https://paywall.example.com/",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "fetch_failed"
    assert result.tier == Tier.TIER_5
    assert classifier.calls == []
