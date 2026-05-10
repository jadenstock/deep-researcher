"""Fetch tool - pull a URL and return its main content as markdown.

Wraps `retrieval.fetch.fetch_and_extract`. Caps the returned markdown
so one enormous page can't blow the agent's context window; the agent
can always call `fetch_url` again asking for a different URL.
"""

from __future__ import annotations

import logging

from pydantic_ai import ModelRetry, RunContext

from ...retrieval.fetch import fetch_and_extract
from ...schemas.enums import NoteType, SourceState
from ...schemas.ids import NoteID
from ...schemas.note import SourceNoteMetadata
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


# Preview sent back to the scout from scout_fetch. Short enough to keep
# scout context compact; the full cleaned text lives on note.content for
# the analyst to retrieve via load_note.
SCOUT_PREVIEW_CHARS = 600


@instrumented
async def scout_fetch(ctx: RunContext[Deps], source_id: NoteID) -> str:
    """Fetch a source's URL, store cleaned content on the note, return a preview.

    Writes the extracted markdown into `note.content` so downstream
    analysts can deep-read via `load_note(source_id)` without
    re-fetching. Promotes the source from SCOUTED to FETCHED. Returns
    a 2-3 sentence preview excerpt so you (the scout) can tier-guess
    and relevance-guess without carrying the whole page in your
    context.

    Args:
      source_id: NoteID of a source_note you created via
        create_source_note. The URL to fetch is read off the note.

    Returns the preview excerpt string. On fetch failure returns a
    short "unreachable: <reason>" message and leaves `note.content`
    empty - don't deep-read a failed source.
    """
    existing = ctx.deps.memory.get(source_id)
    if existing is None:
        raise ModelRetry(
            f"source_id {source_id!r} not in memory. "
            "Call create_source_note first, then scout_fetch on the returned id."
        )
    if existing.type != NoteType.SOURCE:
        raise ModelRetry(f"note {source_id!r} is a {existing.type.value}, not a source_note.")
    meta = existing.metadata
    assert isinstance(meta, SourceNoteMetadata)

    result = await fetch_and_extract(meta.url)
    if result is None or not result.markdown:
        reason = "connection_failed"
        if result is not None:
            if result.status_code >= 400:
                reason = f"http_{result.status_code}"
            else:
                reason = "no_main_content"
        logger.info("scout_fetch unreachable source=%s reason=%s", source_id, reason)
        return f"unreachable: {reason}"

    md = result.markdown
    truncated = False
    if len(md) > MAX_MARKDOWN_CHARS:
        md = md[:MAX_MARKDOWN_CHARS]
        truncated = True

    # Promote state to FETCHED; upgrade title if the fetched page had a
    # better one and the original was just the URL.
    header_updates: dict[str, object] = {"state": SourceState.FETCHED}
    if result.title and (not meta.title or meta.title == meta.url):
        header_updates["title"] = result.title
    new_meta = meta.model_copy(update=header_updates)

    # Preview = leading chars after stripping heading markers - rough but
    # good enough signal for tier/relevance guess.
    preview = md.strip()[:SCOUT_PREVIEW_CHARS]
    if truncated:
        preview = (
            f"{preview}\n\n"
            f"_(content truncated — full text on note.content capped "
            f"at {MAX_MARKDOWN_CHARS} chars)_"
        )

    await ctx.deps.memory.update(
        source_id,
        title=new_meta.title,
        content=md,
        metadata=new_meta,
    )
    return preview
