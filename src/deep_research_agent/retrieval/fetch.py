"""Fetch a URL and extract its main content to markdown.

Routes by content type: HTML → trafilatura, PDF → MarkItDown. Both
emit the same FetchResult shape so callers don't branch. URLs that
end in `.pdf` or serve `application/pdf` take the MarkItDown path;
everything else goes through trafilatura.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time

import httpx
import trafilatura
from markitdown import MarkItDown
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; deep-research-agent/0.1)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# Single shared MarkItDown instance — its constructor scans for converters,
# which is ~40ms, not something we want per-fetch.
_MARKITDOWN = MarkItDown()

# Hard caps on PDF processing. The PDF path is synchronous and CPU-bound
# (MarkItDown shells out to pdfminer), so one pathological PDF can freeze
# the event loop for minutes if left unbounded. These caps prevent that:
#   - bytes > MAX_PDF_BYTES: drop the PDF entirely (too big to be signal-
#     dense; usually a textbook or scanned archive)
#   - pages > MAX_PDF_PAGES: slice to the first N before conversion
#     (appendices / supplementary are noise for synthesis)
#   - conversion wall time > TIMEOUT: abandon and return no markdown
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 20
PDF_CONVERT_TIMEOUT_S = 45.0


def _is_pdf(url: str, content_type: str | None) -> bool:
    if content_type and "application/pdf" in content_type:
        return True
    return url.lower().split("?", 1)[0].endswith(".pdf")


def _truncate_pdf_pages(raw: bytes, max_pages: int) -> bytes:
    """Return PDF bytes truncated to at most `max_pages`. Falls back to
    the original bytes if pypdf can't parse (encrypted, damaged, etc.) —
    MarkItDown will then try and fail on its own terms.
    """
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        logger.debug("pdf_truncate_parse_failed err=%s", exc)
        return raw
    if len(reader.pages) <= max_pages:
        return raw
    try:
        writer = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except Exception as exc:
        logger.debug("pdf_truncate_rewrite_failed err=%s", exc)
        return raw


def _markitdown_convert_sync(raw: bytes) -> tuple[str | None, str | None]:
    """Blocking MarkItDown conversion. Runs in a worker thread via
    asyncio.to_thread; kept separate so the async caller can wrap it in
    wait_for.
    """
    result = _MARKITDOWN.convert_stream(io.BytesIO(raw), file_extension=".pdf")
    return (result.text_content or None), (result.title or None)


async def _pdf_to_markdown(raw: bytes, url: str) -> tuple[str | None, str | None]:
    """Convert PDF bytes to (markdown, title). Returns (None, None) on
    any failure — oversized, unparseable, or slow PDFs degrade to "no
    body" rather than blowing up the fetch.

    Runs MarkItDown off the event loop with a hard timeout so a single
    pathological PDF can't stall concurrent QS tasks.
    """
    if len(raw) > MAX_PDF_BYTES:
        logger.warning("pdf_too_large url=%s bytes=%d cap=%d", url, len(raw), MAX_PDF_BYTES)
        return None, None
    truncated = _truncate_pdf_pages(raw, MAX_PDF_PAGES)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_markitdown_convert_sync, truncated),
            timeout=PDF_CONVERT_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning(
            "pdf_convert_timeout url=%s bytes=%d timeout=%.0fs",
            url,
            len(truncated),
            PDF_CONVERT_TIMEOUT_S,
        )
        return None, None
    except Exception as exc:
        logger.warning("pdf_convert_failed url=%s err=%s", url, exc)
        return None, None


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
    t_start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.warning("fetch_failed url=%s err=%s elapsed_ms=%d", url, exc, elapsed_ms)
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
        path_taken = "pdf_markitdown"
        markdown, title = await _pdf_to_markdown(resp.content, str(resp.url))
    else:
        path_taken = "html_trafilatura"
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

    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "fetch_ok url=%s path=%s bytes=%d md_chars=%d elapsed_ms=%d",
        url,
        path_taken,
        byte_length,
        len(markdown) if markdown else 0,
        elapsed_ms,
    )

    return FetchResult(
        url=url,
        final_url=str(resp.url),
        status_code=resp.status_code,
        content_type=content_type,
        title=title,
        markdown=markdown,
        byte_length=byte_length,
    )
