"""Search tools - web + academic.

Wrap the existing retrieval clients (Brave, Semantic Scholar, arXiv) as
agent tools. Each tool returns a list of `SearchResult` - a flattened
shape that keeps the in-context payload small.

Agents typically emit several search calls in one turn (web +
academic for the same query, or multiple reformulations); pydantic-ai
dispatches them concurrently.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import RunContext

from ..deps import Deps
from ..events import instrumented
from ..schemas import SearchResult

logger = logging.getLogger(__name__)


@instrumented
async def search_web(ctx: RunContext[Deps], query: str, count: int = 8) -> list[SearchResult]:
    """Run a web search (Brave) for the given query.

    Use this for: current events, tutorials, industry posts, official
    docs, company announcements - anything not primarily in
    peer-reviewed literature. Safe to call multiple times in one turn
    with different query formulations; pydantic-ai dispatches them
    concurrently.

    Args:
      query: Natural-language search query. Think of it like a good
        Google query - keywords matter more than full sentences.
      count: Number of hits to return. Default 8; keep it small
        (5-10) per call since you'll often want to run several
        varied queries in parallel rather than one huge one.

    Returns a list of SearchResult with title / url / snippet /
    source. If no web-search provider is configured (no Brave key),
    returns an empty list - fall back to search_academic.
    """
    if ctx.deps.brave is None:
        logger.info("search_web called but no brave_api_key - returning []")
        return []
    hits = await ctx.deps.brave.search(query, count=count)
    return [
        SearchResult(
            title=h.title,
            url=h.url,
            snippet=h.snippet,
            source=h.source,
            authors=h.authors,
            venue=h.venue,
            year=h.year,
            citation_count=h.citation_count,
        )
        for h in hits
    ]


@instrumented
async def search_academic(ctx: RunContext[Deps], query: str, limit: int = 6) -> list[SearchResult]:
    """Run an academic search across Semantic Scholar + arXiv in parallel.

    Use this for: anything where peer-reviewed literature, preprints,
    or benchmarks matter - methods, empirical claims, state-of-the-art,
    citation trails. Results carry authors / venue / year /
    citation_count when available, which helps tier classification.

    Args:
      query: Natural-language search query. Academic search engines
        do best with specific technical terms, author names, paper
        titles, or concept keywords.
      limit: Max hits PER PROVIDER (not total). Default 6. Final
        list is deduped by URL, so expect up to ~2x this many hits.

    Returns a list of SearchResult with title / url / snippet /
    source / authors / venue / year / citation_count.
    """
    s2, ax = await asyncio.gather(
        ctx.deps.semantic_scholar.search(query, limit=limit),
        ctx.deps.arxiv.search(query, limit=limit),
        return_exceptions=True,
    )
    hits = []
    if isinstance(s2, list):
        hits.extend(s2)
    else:
        logger.warning("search_academic semantic_scholar failed: %s", s2)
    if isinstance(ax, list):
        hits.extend(ax)
    else:
        logger.warning("search_academic arxiv failed: %s", ax)
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for h in hits:
        if h.url in seen:
            continue
        seen.add(h.url)
        deduped.append(
            SearchResult(
                title=h.title,
                url=h.url,
                snippet=h.snippet,
                source=h.source,
                authors=h.authors,
                venue=h.venue,
                year=h.year,
                citation_count=h.citation_count,
            )
        )
    return deduped
