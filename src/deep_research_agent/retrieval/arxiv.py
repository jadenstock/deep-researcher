"""arXiv paper search.

arXiv returns an Atom feed; we parse it with the stdlib and emit
SearchHit-shaped results. No API key; a modest throttle keeps us
under arXiv's published 1 req/3s guideline for the public endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
from xml.etree import ElementTree as ET

import httpx

from .brave import SearchHit

logger = logging.getLogger(__name__)

ARXIV_QUERY_URL = "https://export.arxiv.org/api/query"

_ARXIV_LOCK = asyncio.Lock()
_ARXIV_LAST_CALL_AT = 0.0
_ARXIV_MIN_INTERVAL_S = 3.0

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


async def _arxiv_throttle() -> None:
    global _ARXIV_LAST_CALL_AT
    async with _ARXIV_LOCK:
        wait = _ARXIV_MIN_INTERVAL_S - (time.monotonic() - _ARXIV_LAST_CALL_AT)
        if wait > 0:
            await asyncio.sleep(wait)
        _ARXIV_LAST_CALL_AT = time.monotonic()


def _parse_feed(xml_text: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("arxiv_parse_failed err=%s", exc)
        return hits
    for entry in root.findall("atom:entry", _NS):
        title_el = entry.find("atom:title", _NS)
        summary_el = entry.find("atom:summary", _NS)
        published_el = entry.find("atom:published", _NS)
        id_el = entry.find("atom:id", _NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        snippet = (summary_el.text or "").strip() if summary_el is not None else ""
        abs_url = (id_el.text or "").strip() if id_el is not None else ""
        if not title or not abs_url:
            continue

        authors: list[str] = []
        for a in entry.findall("atom:author", _NS):
            name_el = a.find("atom:name", _NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        year: int | None = None
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except ValueError:
                year = None

        pdf_url: str | None = None
        for link in entry.findall("atom:link", _NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                href = link.get("href")
                if href:
                    pdf_url = href
                    break

        hits.append(
            SearchHit(
                title=title,
                url=abs_url,
                snippet=snippet[:600],
                source="arxiv",
                authors=authors,
                venue="arXiv",
                year=year,
                pdf_url=pdf_url,
            )
        )
    return hits


class ArxivClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Return up to `limit` arXiv papers matching `query`.

        Uses the all-fields query (`all:`) so title/abstract/author text
        all match. Returns an empty list on API failure.
        """
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(limit, 20),
            "sortBy": "relevance",
        }
        await _arxiv_throttle()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(ARXIV_QUERY_URL, params=params)
        except httpx.HTTPError as exc:
            logger.warning("arxiv_search_failed query=%r err=%s", query[:60], exc)
            return []

        if resp.status_code >= 400:
            logger.warning("arxiv_search_non_2xx query=%r status=%d", query[:60], resp.status_code)
            return []

        hits = _parse_feed(resp.text)
        logger.info("arxiv_search query=%r hits=%d", query[:60], len(hits))
        return hits
