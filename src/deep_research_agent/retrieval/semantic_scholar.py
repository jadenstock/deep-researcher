"""Semantic Scholar paper search.

Returns SearchHit-shaped results with academic metadata populated
(authors, venue, year, citation_count, doi, pdf_url). Unauthenticated
requests work but are rate-limited; setting
`local.retrieval.semantic_scholar_api_key` lifts the limit.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .brave import SearchHit

logger = logging.getLogger(__name__)

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

# S2 unauthenticated tier is ~100 req / 5min. We only make 1 request per
# QS so a modest throttle is ample; the lock just avoids bursting when
# sub-questions dispatch in parallel.
_S2_LOCK = asyncio.Lock()
_S2_LAST_CALL_AT = 0.0
_S2_MIN_INTERVAL_S = 1.0


async def _s2_throttle() -> None:
    global _S2_LAST_CALL_AT
    async with _S2_LOCK:
        wait = _S2_MIN_INTERVAL_S - (time.monotonic() - _S2_LAST_CALL_AT)
        if wait > 0:
            await asyncio.sleep(wait)
        _S2_LAST_CALL_AT = time.monotonic()


# Fields we pull; keep minimal to stay under S2's per-field response cap.
_S2_FIELDS = "title,abstract,authors,venue,year,citationCount,openAccessPdf,externalIds,url"


class SemanticScholarClient:
    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Return up to `limit` papers matching `query`.

        Returns an empty list on any API error — academic search is
        additive; a failure should not break the run.
        """
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        params = {"query": query, "limit": min(limit, 20), "fields": _S2_FIELDS}

        await _s2_throttle()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(S2_SEARCH_URL, headers=headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("s2_search_failed query=%r err=%s", query[:60], exc)
            return []

        if resp.status_code >= 400:
            logger.warning(
                "s2_search_non_2xx query=%r status=%d body=%s",
                query[:60],
                resp.status_code,
                resp.text[:200],
            )
            return []

        data = resp.json()
        papers = data.get("data", []) or []
        hits: list[SearchHit] = []
        for p in papers:
            title = p.get("title") or ""
            if not title:
                continue
            abstract = p.get("abstract") or ""
            authors = [a.get("name", "") for a in p.get("authors", []) or [] if a.get("name")]
            venue = p.get("venue") or None
            year = p.get("year")
            citation_count = p.get("citationCount")
            external = p.get("externalIds") or {}
            doi = external.get("DOI")
            arxiv_id = external.get("ArXiv")
            pmc_id = external.get("PubMedCentral")
            oa = p.get("openAccessPdf") or {}
            pdf_url = oa.get("url") or None
            # URL preference: HTML-native renderings first (arXiv HTML,
            # PMC HTML) so the fetcher takes the fast trafilatura path
            # instead of MarkItDown on a PDF. DOI landing page next, then
            # the PDF URL, then the S2 page as last resort.
            html_url: str | None = None
            if arxiv_id:
                html_url = f"https://arxiv.org/html/{arxiv_id}"
            elif pmc_id:
                pmc_num = pmc_id if str(pmc_id).startswith("PMC") else f"PMC{pmc_id}"
                html_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_num}/"
            url = (
                html_url
                or (f"https://doi.org/{doi}" if doi else None)
                or pdf_url
                or p.get("url")
                or ""
            )
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=abstract[:600],
                    source="semantic_scholar",
                    authors=authors,
                    venue=venue,
                    year=year,
                    citation_count=citation_count,
                    doi=doi,
                    pdf_url=pdf_url,
                )
            )
        logger.info("s2_search query=%r hits=%d", query[:60], len(hits))
        return hits
