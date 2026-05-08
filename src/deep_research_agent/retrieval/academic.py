"""Unified academic search — Semantic Scholar + arXiv, dedup'd,
with optional Unpaywall DOI rescue.

The facade's job is to hide the difference between paper sources: the
caller just asks for `search_academic(query, limit)` and gets a list of
SearchHit objects with academic metadata populated.

Dedup strategy:
- Prefer S2 hits when the same paper appears in both (S2 has citation
  count and verified venue info).
- Match on (DOI) first, else normalized title.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..config import LocalConfig
from .arxiv import ArxivClient
from .brave import SearchHit
from .semantic_scholar import SemanticScholarClient
from .unpaywall import UnpaywallClient

logger = logging.getLogger(__name__)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()


def _dedup(hits: list[SearchHit]) -> list[SearchHit]:
    """Keep first-seen by DOI, then by normalized title."""
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    out: list[SearchHit] = []
    for h in hits:
        if h.doi and h.doi.lower() in seen_doi:
            continue
        key = _normalize_title(h.title)
        if key and key in seen_title:
            continue
        if h.doi:
            seen_doi.add(h.doi.lower())
        if key:
            seen_title.add(key)
        out.append(h)
    return out


async def search_academic(
    query: str,
    *,
    local: LocalConfig,
    limit_per_source: int = 3,
) -> list[SearchHit]:
    """Run Semantic Scholar + arXiv in parallel, dedup, optionally rescue
    paywalled S2 hits via Unpaywall. Returns up to ~2x`limit_per_source`
    unique hits. Errors from any one source don't break the combined
    result - each client returns [] on failure.
    """
    s2 = SemanticScholarClient(api_key=local.retrieval.semantic_scholar_api_key)
    ax = ArxivClient()
    s2_hits, ax_hits = await asyncio.gather(
        s2.search(query, limit=limit_per_source),
        ax.search(query, limit=limit_per_source),
    )
    # Interleave S2 first so its richer metadata wins on dedup ties.
    combined = _dedup([*s2_hits, *ax_hits])

    email = local.retrieval.unpaywall_email
    if email:
        up = UnpaywallClient(email=email)

        async def _rescue(h: SearchHit) -> SearchHit:
            # Only rescue hits with a DOI that don't already have a PDF URL.
            # If the current URL is already an HTML rendering (arXiv HTML,
            # PMC HTML), keep it — the fetcher will take the fast path
            # there. Only overwrite when we'd otherwise hit a DOI landing
            # page (which is typically paywalled).
            if h.doi and not h.pdf_url:
                oa = await up.find_oa_pdf(h.doi)
                if oa:
                    is_html_landing = (
                        "arxiv.org/html/" in h.url or "ncbi.nlm.nih.gov/pmc/articles/" in h.url
                    )
                    update = {"pdf_url": oa}
                    if not is_html_landing:
                        update["url"] = oa
                    return h.model_copy(update=update)
            return h

        combined = list(await asyncio.gather(*(_rescue(h) for h in combined)))

    logger.info(
        "academic_search query=%r s2=%d arxiv=%d dedup=%d",
        query[:60],
        len(s2_hits),
        len(ax_hits),
        len(combined),
    )
    return combined
