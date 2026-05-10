"""Fetch tool - pull a URL and return its main content as markdown.

Wraps `retrieval.fetch.fetch_and_extract`. Caps the returned markdown
so one enormous page can't blow the agent's context window; the agent
can always call `fetch_url` again asking for a different URL.
"""

from __future__ import annotations

import logging

from pydantic_ai import ModelRetry, RunContext

from ...retrieval.fetch import FetchResult, fetch_and_extract
from ...schemas.enums import NoteType, SourceState
from ...schemas.ids import NoteID
from ...schemas.note import SourceNoteMetadata
from ...schemas.source import ContentKind
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

# Below this length, treat extracted content as likely abstract/preview
# rather than full body text. arXiv abs pages and DOI landing stubs
# typically produce 1-3KB of markdown through trafilatura; a real HTML
# paper render is usually 15KB+. 4K is a generous ceiling that still
# flags the common "abstract only" case.
ABSTRACT_ONLY_THRESHOLD_CHARS = 4000


def _fetch_failure_reason(result: FetchResult | None) -> str:
    if result is None:
        return "connection_failed"
    if result.status_code >= 400:
        return f"http_{result.status_code}"
    return "no_main_content"


@instrumented
async def scout_fetch(ctx: RunContext[Deps], source_id: NoteID) -> str:
    """Fetch a source's URL, store cleaned content on the note, return a preview.

    Tries the note's primary `url` first (HTML → trafilatura). If that
    returns nothing or looks abstract-only AND the note carries a
    `pdf_url`, falls back to the PDF (→ MarkItDown). The longer of the
    two extractions wins.

    Writes the extracted markdown into `note.content` so downstream
    analysts can deep-read via `load_note(source_id)` without
    re-fetching. Promotes the source from SCOUTED to FETCHED. Stamps
    `content_kind` on the metadata so callers know whether the stored
    body is full_text, abstract_only, or unavailable.

    Args:
      source_id: NoteID of a source_note you created via
        create_source_note. The URL (and optional pdf_url) are read
        off the note.

    Returns a short preview excerpt. For abstract-only sources the
    preview is prefixed with "[abstract-only] " so the scout records
    the limitation. On total fetch failure returns "unreachable:
    <reason>" and leaves `note.content` empty.
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

    primary_result = await fetch_and_extract(meta.url)
    primary_md = primary_result.markdown if primary_result else None
    primary_len = len(primary_md) if primary_md else 0

    # Fall back to the PDF when HTML was missing or thin. Only bother
    # hitting the PDF if the primary URL and pdf_url differ - some S2
    # hits surface the same PDF in both slots.
    fallback_result: FetchResult | None = None
    fallback_md: str | None = None
    if meta.pdf_url and meta.pdf_url != meta.url and primary_len < ABSTRACT_ONLY_THRESHOLD_CHARS:
        fallback_result = await fetch_and_extract(meta.pdf_url)
        fallback_md = fallback_result.markdown if fallback_result else None

    # Pick the extraction with more body. Ties go to the primary so we
    # don't churn if the PDF returned the same abstract.
    fallback_len = len(fallback_md) if fallback_md else 0
    if fallback_md and fallback_len > primary_len:
        chosen_md = fallback_md
        chosen_result = fallback_result
        chosen_source = "pdf_fallback"
    elif primary_md:
        chosen_md = primary_md
        chosen_result = primary_result
        chosen_source = "primary"
    else:
        chosen_md = None
        chosen_result = None
        chosen_source = "none"

    if not chosen_md:
        reason = _fetch_failure_reason(primary_result)
        if fallback_result is not None:
            reason = f"{reason}; pdf_fallback: {_fetch_failure_reason(fallback_result)}"
        header_updates: dict[str, object] = {
            "state": SourceState.FETCHED,
            "content_kind": "unavailable",
        }
        new_meta = meta.model_copy(update=header_updates)
        await ctx.deps.memory.update(source_id, metadata=new_meta)
        logger.info("scout_fetch unreachable source=%s reason=%s", source_id, reason)
        return f"unreachable: {reason}"

    truncated = False
    if len(chosen_md) > MAX_MARKDOWN_CHARS:
        chosen_md = chosen_md[:MAX_MARKDOWN_CHARS]
        truncated = True

    content_kind: ContentKind = (
        "full_text" if len(chosen_md) >= ABSTRACT_ONLY_THRESHOLD_CHARS else "abstract_only"
    )

    header_updates = {
        "state": SourceState.FETCHED,
        "content_kind": content_kind,
    }
    if (
        chosen_result is not None
        and chosen_result.title
        and (not meta.title or meta.title == meta.url)
    ):
        header_updates["title"] = chosen_result.title
    new_meta = meta.model_copy(update=header_updates)

    preview_body = chosen_md.strip()[:SCOUT_PREVIEW_CHARS]
    if content_kind == "abstract_only":
        preview = (
            f"[abstract-only] {preview_body}\n\n"
            f"_(short content — analyst should treat this as preview/summary, "
            f"not full body text)_"
        )
    elif truncated:
        preview = (
            f"{preview_body}\n\n"
            f"_(content truncated — full text on note.content capped "
            f"at {MAX_MARKDOWN_CHARS} chars)_"
        )
    else:
        preview = preview_body

    await ctx.deps.memory.update(
        source_id,
        title=new_meta.title,
        content=chosen_md,
        metadata=new_meta,
    )
    logger.info(
        "scout_fetch ok source=%s via=%s chars=%d kind=%s",
        source_id,
        chosen_source,
        len(chosen_md),
        content_kind,
    )
    return preview
