"""Brave Search web client.

Small async client over the Brave Search API. Returns a normalized
`SearchHit` so swapping to a different provider (Tavily, Serper)
requires only another client that emits the same shape.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


class BraveSearchError(RuntimeError):
    """Brave API returned a non-2xx response."""


class BraveClient:
    def __init__(self, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, count: int = 10) -> list[SearchHit]:
        """Return up to `count` web results for `query`."""
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
        }
        params = {"q": query, "count": min(count, 20)}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
        if resp.status_code >= 400:
            raise BraveSearchError(f"Brave search {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        results = data.get("web", {}).get("results", []) or []
        hits = [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in results
        ]
        logger.info("brave_search query=%r hits=%d", query, len(hits))
        return hits
