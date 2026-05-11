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
import re
from typing import Literal

from pydantic_ai import ModelRetry, RunContext

from ...retrieval.brave import SearchHit
from ...schemas.enums import NoteType
from ...schemas.ids import NoteID
from ...schemas.note import SourceNoteMetadata
from ..deps import Deps
from ..events import instrumented
from ..schemas import SearchResult

logger = logging.getLogger(__name__)


def _hit_to_result(h: SearchHit) -> SearchResult:
    return SearchResult(
        title=h.title,
        url=h.url,
        snippet=h.snippet,
        source=h.source,
        authors=h.authors,
        venue=h.venue,
        year=h.year,
        citation_count=h.citation_count,
        pdf_url=h.pdf_url,
        doi=h.doi,
    )


# Extract an arXiv id from any arxiv.org URL (abs / pdf / html). Used as
# the fallback when a source note has no DOI but a recognizable arXiv
# URL - S2 accepts `ARXIV:{id}` as a paper_id.
_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/([^/\s?#]+?)(?:v\d+)?(?:\.pdf)?(?:[/?#]|$)",
    re.IGNORECASE,
)


def _source_to_s2_paper_id(meta: SourceNoteMetadata) -> str | None:
    """Resolve a source note's metadata to a Semantic Scholar paper_id.

    Returns `DOI:{doi}` when a DOI is on the note, else `ARXIV:{id}`
    when the URL parses as an arXiv link, else None (caller handles
    the miss).
    """
    if meta.doi:
        return f"DOI:{meta.doi}"
    m = _ARXIV_URL_RE.search(meta.url)
    if m:
        return f"ARXIV:{m.group(1)}"
    return None


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
    return [_hit_to_result(h) for h in hits]


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
        deduped.append(_hit_to_result(h))
    return deduped


@instrumented
async def find_related_papers(
    ctx: RunContext[Deps],
    source_id: NoteID,
    direction: Literal["citing", "cited_by"],
    limit: int = 20,
) -> list[SearchResult]:
    """Traverse the citation graph from an existing source note via Semantic Scholar.

    Use this when you've found a seed paper that's clearly on-angle and
    you want a curated bibliography rather than more keyword searches.
    Citation traversal is usually much higher signal than lexical
    search on niche topics - one good paper's citation list often
    yields more relevant work than 10 reformulated queries.

    Args:
      source_id: NoteID of an existing source_note (from
        create_source_note). The note must have either a DOI or an
        arXiv URL; otherwise the lookup fails with a ModelRetry.
      direction: "citing" returns papers that cite the seed (forward
        traversal - later work building on it). "cited_by" returns
        papers the seed itself cites (backward traversal - the seed's
        bibliography).
      limit: Max papers to return. Default 20; S2 caps at 50.

    Returns a list of SearchResult that you can feed into
    create_source_note (remember to forward pdf_url and doi). Does
    NOT create source notes for you - the scout decides which
    results are worth recording.
    """
    note = ctx.deps.memory.get(source_id)
    if note is None:
        raise ModelRetry(
            f"source_id {source_id!r} not in memory. "
            "Pass a source_note id you created via create_source_note."
        )
    if note.type != NoteType.SOURCE:
        raise ModelRetry(f"note {source_id!r} is a {note.type.value}, not a source_note.")
    meta = note.metadata
    assert isinstance(meta, SourceNoteMetadata)

    paper_id = _source_to_s2_paper_id(meta)
    if paper_id is None:
        raise ModelRetry(
            f"source {source_id!r} has no DOI and its URL is not arXiv - "
            "can't look up citations. Try another seed source with a DOI."
        )

    if direction == "citing":
        hits = await ctx.deps.semantic_scholar.get_citations(paper_id, limit=limit)
    else:
        hits = await ctx.deps.semantic_scholar.get_references(paper_id, limit=limit)

    return [_hit_to_result(h) for h in hits]
