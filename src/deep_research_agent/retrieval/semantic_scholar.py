"""Semantic Scholar paper search.

Returns SearchHit-shaped results with academic metadata populated
(authors, venue, year, citation_count, doi, pdf_url). Unauthenticated
requests work but are rate-limited; setting
`local.retrieval.semantic_scholar_api_key` lifts the limit.
"""

from __future__ import annotations

import logging

import httpx

from ._http import request_with_429_retry
from .arxiv import arxiv_html_url_from_id
from .brave import SearchHit
from .rate_limit import get_bucket

logger = logging.getLogger(__name__)

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER_BASE = "https://api.semanticscholar.org/graph/v1/paper"

# Defaults by auth state:
#   unauthenticated: ~100 req / 5min -> 3.0s interval (0.33/s)
#   authenticated:   ~1/s per key on /paper/search
# Picked in set_s2_min_interval() when config wires it up; bucket starts at
# the unauthenticated default so an un-wired import can't exceed the public
# quota.
_S2_INTERVAL_UNAUTH_S = 3.0
_S2_INTERVAL_AUTH_S = 1.0


def _s2_bucket():
    return get_bucket("semantic_scholar", rate=1.0 / _S2_INTERVAL_UNAUTH_S)


def set_s2_min_interval(interval_s: float | None, *, authenticated: bool) -> None:
    """Configure the Semantic Scholar rate limit.

    If `interval_s` is None, picks a default based on `authenticated`:
    3.0s unauthenticated (matches ~100 req/5min public quota), 1.0s
    authenticated. Callers who know their plan allows more can pass an
    explicit smaller value.
    """
    if interval_s is None:
        interval_s = _S2_INTERVAL_AUTH_S if authenticated else _S2_INTERVAL_UNAUTH_S
    interval_s = max(0.01, interval_s)
    _s2_bucket().set_rate(rate=1.0 / interval_s)


# Fields we pull; keep minimal to stay under S2's per-field response cap.
_S2_FIELDS = "title,abstract,authors,venue,year,citationCount,openAccessPdf,externalIds,url"


def _paper_to_hit(p: dict) -> SearchHit | None:
    """Normalize a Semantic Scholar paper object into a SearchHit.

    Returns None if the paper lacks the minimum fields (title + some
    URL we can land on). Used by both the search endpoint and the
    citations / references endpoints.

    URL preference: HTML-native renderings first (arXiv HTML, PMC HTML)
    so the fetcher takes the fast trafilatura path instead of MarkItDown
    on a PDF. DOI landing page next, then the PDF URL, then the S2 page
    as last resort.
    """
    title = p.get("title") or ""
    if not title:
        return None
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
    html_url: str | None = None
    if arxiv_id:
        html_url = arxiv_html_url_from_id(arxiv_id)
    elif pmc_id:
        pmc_num = pmc_id if str(pmc_id).startswith("PMC") else f"PMC{pmc_id}"
        html_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_num}/"
    url = html_url or (f"https://doi.org/{doi}" if doi else None) or pdf_url or p.get("url") or ""
    if not url:
        return None
    return SearchHit(
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


class SemanticScholarClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    async def _request_json(
        self,
        url: str,
        params: dict,
        *,
        log_label: str,
        log_key: str,
    ) -> dict | None:
        """GET `url` with S2 rate-limit + 429 retry handling.

        Returns the decoded JSON body, or None on any terminal failure
        (connection error, exhausted retries, 4xx/5xx). Shared by
        `search`, `get_citations`, and `get_references` so retry
        behavior is consistent across endpoints.
        """
        try:
            resp = await request_with_429_retry(
                self._client,
                url,
                params=params,
                headers=self._headers(),
                bucket=_s2_bucket(),
                log_label=log_label,
                log_key=log_key,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("%s_failed %s err=%s", log_label, log_key, exc)
            return None
        if resp.status_code >= 400:
            logger.warning(
                "%s_non_2xx %s status=%d body=%s",
                log_label,
                log_key,
                resp.status_code,
                resp.text[:200],
            )
            return None
        return resp.json()

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Return up to `limit` papers matching `query`.

        Returns [] on any terminal API error - academic search is
        additive; a failure should not break the run.
        """
        params = {"query": query, "limit": min(limit, 20), "fields": _S2_FIELDS}
        data = await self._request_json(
            S2_SEARCH_URL, params, log_label="s2_search", log_key=f"query={query[:120]!r}"
        )
        if data is None:
            return []
        papers = data.get("data", []) or []
        hits = [h for h in (_paper_to_hit(p) for p in papers) if h is not None]
        logger.info("s2_search query=%r hits=%d", query[:120], len(hits))
        return hits

    async def _traverse(
        self,
        paper_id: str,
        *,
        endpoint: str,
        row_key: str,
        log_label: str,
        limit: int,
    ) -> list[SearchHit]:
        """Follow a paper's citation graph. Shared by citations/references."""
        url = f"{S2_PAPER_BASE}/{paper_id}/{endpoint}"
        params = {"limit": min(limit, 50), "fields": _S2_FIELDS}
        data = await self._request_json(
            url, params, log_label=log_label, log_key=f"paper_id={paper_id!r}"
        )
        if data is None:
            return []
        rows = data.get("data", []) or []
        hits = [h for h in (_paper_to_hit(row.get(row_key) or {}) for row in rows) if h is not None]
        logger.info("%s paper_id=%r hits=%d", log_label, paper_id, len(hits))
        return hits

    async def get_citations(self, paper_id: str, limit: int = 20) -> list[SearchHit]:
        """Return papers that cite `paper_id` (forward citation graph).

        `paper_id` uses S2's prefixed-id format: `DOI:10.xxx/yyy`,
        `ARXIV:2401.12345`, `CorpusID:N`, etc. Returns [] on any
        terminal API error.
        """
        return await self._traverse(
            paper_id,
            endpoint="citations",
            row_key="citingPaper",
            log_label="s2_citations",
            limit=limit,
        )

    async def get_references(self, paper_id: str, limit: int = 20) -> list[SearchHit]:
        """Return papers that `paper_id` cites (backward bibliography)."""
        return await self._traverse(
            paper_id,
            endpoint="references",
            row_key="citedPaper",
            log_label="s2_references",
            limit=limit,
        )
