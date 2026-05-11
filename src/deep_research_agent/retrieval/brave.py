"""Brave Search web client.

Small async client over the Brave Search API. Returns a normalized
`SearchHit` so swapping to a different provider (Tavily, Serper)
requires only another client that emits the same shape.
"""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import BaseModel

from ._http import request_with_429_retry
from .rate_limit import get_bucket

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Brave free tier is 1 QPS with a strict sliding window; 1.5s min-interval
# (rate ~0.67/s) is safe in practice. Paid plans can raise this via
# set_brave_min_interval().
_BRAVE_DEFAULT_INTERVAL_S = 1.5


def _brave_bucket():
    return get_bucket("brave", rate=1.0 / _BRAVE_DEFAULT_INTERVAL_S)


def set_brave_min_interval(interval_s: float) -> None:
    """Override the cross-client Brave rate (as a min interval in seconds)."""
    interval_s = max(0.01, interval_s)
    _brave_bucket().set_rate(rate=1.0 / interval_s)


class SearchHit(BaseModel):
    """Normalized search hit across providers (Brave, Semantic Scholar, arXiv).

    Core fields (title/url/snippet) are populated by every provider.
    Academic fields (authors/venue/year/citation_count/doi/pdf_url) are
    optional; Brave leaves them empty, academic clients fill them in so
    the tier classifier sees abstract-quality snippets and so the
    source_note can record authors/venue without a second fetch.
    """

    title: str
    url: str
    snippet: str = ""
    source: str = "brave"  # provider name - brave / semantic_scholar / arxiv
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    citation_count: int | None = None
    doi: str | None = None
    pdf_url: str | None = None


class BraveSearchError(RuntimeError):
    """Brave API returned a non-2xx response."""


class BraveClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, timeout: float = 15.0) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, count: int = 10) -> list[SearchHit]:
        """Return up to `count` web results for `query`.

        Retries on 429 (see retrieval._http.request_with_429_retry);
        other 4xx/5xx raise BraveSearchError immediately - retrying a
        403 won't help, and retrying a 500 is debatable but not worth
        the complexity for v0.
        """
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {"q": query, "count": min(count, 20)}
        logger.debug("brave_search_start query=%r count=%d", query[:160], params["count"])
        t0 = time.monotonic()
        resp = await request_with_429_retry(
            self._client,
            BRAVE_SEARCH_URL,
            params=params,
            headers=headers,
            bucket=_brave_bucket(),
            log_label="brave",
            log_key=f"query={query[:160]!r}",
            timeout=self._timeout,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code >= 400:
            # Surface rate-limit hints on terminal 429 (exhausted
            # retries) and on other 4xx/5xx. x-ratelimit-* tell us
            # about plan quota.
            retry_after = resp.headers.get("retry-after")
            rl_remaining = resp.headers.get("x-ratelimit-remaining")
            rl_reset = resp.headers.get("x-ratelimit-reset")
            logger.warning(
                "brave_search_error status=%d retry_after=%s "
                "rl_remaining=%s rl_reset=%s elapsed_ms=%d body=%s",
                resp.status_code,
                retry_after,
                rl_remaining,
                rl_reset,
                elapsed_ms,
                resp.text[:200],
            )
            raise BraveSearchError(f"Brave search {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        results = data.get("web", {}).get("results", []) or []
        hits = [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
                source="brave",
            )
            for r in results
        ]
        logger.info(
            "brave_search query=%r hits=%d elapsed_ms=%d",
            query[:160],
            len(hits),
            elapsed_ms,
        )
        return hits
