"""LLM-assisted filenames for downloaded reports."""

from __future__ import annotations

import logging
import re
import unicodedata

import httpx
from openai import AsyncOpenAI

from ..config import LocalConfig, RoutingConfig
from ..schemas.enums import RoleClass, TaskTier

logger = logging.getLogger(__name__)

_MAX_EXCERPT_CHARS = 5_000
_MAX_FILENAME_CHARS = 80
_FILENAME_TIMEOUT_S = 20.0


def report_excerpt(markdown: str, max_chars: int = _MAX_EXCERPT_CHARS) -> str:
    """Return the top slice of a report used for filename generation."""
    compact = re.sub(r"\n{3,}", "\n\n", markdown.strip())
    return compact[:max_chars].strip()


def sanitize_report_filename(candidate: str, *, fallback: str = "research-report") -> str:
    """Convert model output into a safe markdown filename."""
    stem = candidate.strip().lower()
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"['`\"]", "", stem)
    stem = re.sub(r"\.md$", "", stem)
    stem = re.sub(r"&", " and ", stem)
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    if not stem:
        stem = fallback
    stem = stem[:_MAX_FILENAME_CHARS].strip("-") or fallback
    return f"{stem}.md"


def fallback_report_filename(query: str, run_id: str) -> str:
    filename = sanitize_report_filename(query)
    return filename if filename != "research-report.md" else f"{run_id}.md"


async def suggest_report_filename(
    *,
    local: LocalConfig,
    routing: RoutingConfig,
    query: str,
    report_markdown: str,
    run_id: str,
) -> str:
    """Ask the cheap deterministic model for a concise download filename.

    The default routing maps this slot to Haiku. If the model call fails
    or returns an unusable string, callers still get a deterministic
    local fallback.
    """
    excerpt = report_excerpt(report_markdown)
    if not excerpt:
        return fallback_report_filename(query, run_id)

    model_id = routing.model_id_for(RoleClass.CHEAP_DETERMINISTIC, TaskTier.LOW)
    fallback = fallback_report_filename(query, run_id)
    try:
        async with httpx.AsyncClient(timeout=_FILENAME_TIMEOUT_S) as http_client:
            client = AsyncOpenAI(
                base_url=local.llm.api_base_url,
                api_key=local.llm.api_key,
                http_client=http_client,
            )
            response = await client.chat.completions.create(
                model=RoutingConfig.router_name(model_id),
                temperature=0,
                max_tokens=24,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Generate one concise filesystem-safe markdown filename stem. "
                            "Use 3-8 descriptive lowercase words separated by hyphens. "
                            "Do not include an extension, quotes, commentary, or punctuation."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Research query:\n{query.strip()}\n\n"
                            f"Top of report:\n{excerpt}"
                        ),
                    },
                ],
            )
    except Exception:
        logger.exception("report filename suggestion failed run_id=%s model=%s", run_id, model_id)
        return fallback

    text = response.choices[0].message.content if response.choices else ""
    filename = sanitize_report_filename(text or "", fallback=fallback.removesuffix(".md"))
    return filename
