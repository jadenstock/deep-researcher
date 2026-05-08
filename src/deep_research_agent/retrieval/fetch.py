"""Fetch a URL and extract its main content to markdown.

Routes by content type: HTML → trafilatura, PDF → MarkItDown. Both
emit the same FetchResult shape so callers don't branch. URLs that
end in `.pdf` or serve `application/pdf` take the MarkItDown path;
everything else goes through trafilatura.
"""

from __future__ import annotations

import io
import logging

import httpx
import trafilatura
from markitdown import MarkItDown
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; deep-research-agent/0.1)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# Single shared MarkItDown instance — its constructor scans for converters,
# which is ~40ms, not something we want per-fetch.
_MARKITDOWN = MarkItDown()


def _is_pdf(url: str, content_type: str | None) -> bool:
    if content_type and "application/pdf" in content_type:
        return True
    return url.lower().split("?", 1)[0].endswith(".pdf")


def _pdf_to_markdown(raw: bytes, url: str) -> tuple[str | None, str | None]:
    """Convert PDF bytes to (markdown, title). Returns (None, None) on failure.

    MarkItDown raises on malformed PDFs; we log and return None rather
    than failing the outer fetch — a bad PDF is the same to the pipeline
    as a page that trafilatura can't extract.
    """
    try:
        result = _MARKITDOWN.convert_stream(io.BytesIO(raw), file_extension=".pdf")
    except Exception as exc:
        logger.warning("pdf_convert_failed url=%s err=%s", url, exc)
        return None, None
    return (result.text_content or None), (result.title or None)


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

    markdown: str | None
    title: str | None = None

    if _is_pdf(str(resp.url), content_type):
        markdown, title = _pdf_to_markdown(resp.content, str(resp.url))
    else:
        html = resp.text
        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
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
