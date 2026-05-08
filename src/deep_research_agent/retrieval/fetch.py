"""Fetch a URL and extract its main content to markdown.

HTML only for v0 (most research-y pages). PDF path lands in v2 alongside
the academic-source milestone — it uses markitdown and falls under the
same FetchResult shape so callers don't branch.
"""

from __future__ import annotations

import logging

import httpx
import trafilatura
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; deep-research-agent/0.1)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchResult(BaseModel):
    url: str
    final_url: str
    status_code: int
    content_type: str | None = None
    title: str | None = None
    markdown: str | None = None
    byte_length: int = 0


async def fetch_and_extract(url: str, timeout: float = 20.0) -> FetchResult | None:
    """Fetch `url` and extract the main content as markdown.

    Returns None on connection-level failure. Returns a FetchResult with
    markdown=None on non-2xx responses or when the extractor yields
    nothing (e.g., paywall, JS-only page). Callers should tolerate None
    markdown — some candidates will always fail to extract.
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("fetch_failed url=%s err=%s", url, exc)
        return None

    content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip() or None
    byte_length = len(resp.content)

    if resp.status_code >= 400:
        logger.warning("fetch_non_2xx url=%s status=%d", url, resp.status_code)
        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status_code=resp.status_code,
            content_type=content_type,
            byte_length=byte_length,
        )

    html = resp.text
    markdown = trafilatura.extract(
        html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )

    title: str | None = None
    try:
        metadata = trafilatura.extract_metadata(html)
        if metadata is not None:
            title = metadata.title
    except Exception as exc:
        # trafilatura.extract_metadata can raise on malformed input; a missing
        # title is not fatal and callers should not lose the rest of the result.
        logger.debug("metadata_extract_failed url=%s err=%s", url, exc)

    return FetchResult(
        url=url,
        final_url=str(resp.url),
        status_code=resp.status_code,
        content_type=content_type,
        title=title,
        markdown=markdown,
        byte_length=byte_length,
    )
