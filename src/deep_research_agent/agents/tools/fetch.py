"""Fetch tool - pull a URL and return its main content as markdown.

Wraps `retrieval.fetch.fetch_and_extract`. Caps the returned markdown
so one enormous page can't blow the agent's context window; the agent
can always call `fetch_url` again asking for a different URL.
"""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from ...retrieval.fetch import fetch_and_extract
from ..deps import Deps
from ..events import instrumented
from ..schemas import FetchedContent

logger = logging.getLogger(__name__)

# Hard cap on markdown returned to the agent per fetch. ~60K chars ≈ 15K
# tokens, enough for most papers' main text after trafilatura strips
# navigation + references. Oversized fetches get truncated with a note
# so the agent knows there's more it isn't seeing.
MAX_MARKDOWN_CHARS = 60_000


@instrumented
async def fetch_url(ctx: RunContext[Deps], url: str) -> FetchedContent:
    """Fetch `url` and return its main content as markdown.

    HTML pages go through trafilatura (main-article extraction);
    PDFs through MarkItDown (capped at 15MB / 20 pages). Safe to call
    in parallel on many URLs - pydantic-ai dispatches concurrently.

    Args:
      url: Absolute URL to fetch. Typically the `url` field of a
        SearchResult or the `url` of a source note you created
        earlier. Redirects are followed.

    Returns FetchedContent with:
      - url / final_url / status_code: request/response metadata.
      - markdown: extracted main content, or None on failure.
      - truncated: True if content was cut for length; rare.
      - reason: populated when markdown is None (e.g. "paywall",
        "404", "pdf extraction failed"). Treat as "source
        unreachable" and move to the next candidate.
    """
    del ctx  # ctx required by the @instrumented wrapper, not the impl
    result = await fetch_and_extract(url)
    if result is None:
        return FetchedContent(
            url=url,
            final_url=url,
            status_code=0,
            markdown=None,
            reason="connection_failed",
        )
    truncated = False
    md = result.markdown
    if md and len(md) > MAX_MARKDOWN_CHARS:
        md = md[:MAX_MARKDOWN_CHARS]
        truncated = True
    reason = None
    if md is None:
        reason = f"http_{result.status_code}" if result.status_code >= 400 else "no_main_content"
    return FetchedContent(
        url=result.url,
        final_url=result.final_url,
        status_code=result.status_code,
        title=result.title,
        markdown=md,
        byte_length=result.byte_length,
        truncated=truncated,
        reason=reason,
    )
