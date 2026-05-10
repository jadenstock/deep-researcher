"""Retrieval clients used by the agent tool layer.

Only what the agent tools wrap is re-exported. Each client is a thin
async wrapper around one external provider:

- BraveClient - web search
- SemanticScholarClient - academic metadata + abstracts
- ArxivClient - preprint search
- fetch_and_extract - URL → markdown (HTML via trafilatura, PDF via MarkItDown)
"""

from typing import TYPE_CHECKING

from .arxiv import ArxivClient, set_arxiv_min_interval
from .brave import BraveClient, BraveSearchError, SearchHit, set_brave_min_interval
from .fetch import FetchResult, fetch_and_extract
from .semantic_scholar import SemanticScholarClient, set_s2_min_interval

if TYPE_CHECKING:
    from ..config import RetrievalKeys


def apply_retrieval_rate_limits(keys: "RetrievalKeys") -> None:
    """Wire the process-wide rate-limit buckets from local config.

    Call once at startup (cli / server boot) before any agent runs so
    per-provider caps reflect what the running plan actually allows.
    """
    set_brave_min_interval(keys.brave_min_interval_s)
    set_s2_min_interval(
        keys.semantic_scholar_min_interval_s,
        authenticated=bool(keys.semantic_scholar_api_key),
    )
    set_arxiv_min_interval(keys.arxiv_min_interval_s)


__all__ = [
    "ArxivClient",
    "BraveClient",
    "BraveSearchError",
    "FetchResult",
    "SearchHit",
    "SemanticScholarClient",
    "apply_retrieval_rate_limits",
    "fetch_and_extract",
    "set_arxiv_min_interval",
    "set_brave_min_interval",
    "set_s2_min_interval",
]
