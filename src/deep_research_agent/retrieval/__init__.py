"""Search + fetch + extract retrieval layer.

Web search: Brave (with configurable throttle for free-tier limits).
Academic search: Semantic Scholar + arXiv, with optional Unpaywall
rescue for paywalled DOIs — combined via `search_academic`.
Fetch: httpx + trafilatura for HTML, markitdown for PDFs (v2b).
Cache: diskcache for deterministic replay.
"""

from .academic import search_academic
from .arxiv import ArxivClient
from .brave import BraveClient, BraveSearchError, SearchHit
from .cache import RetrievalCache
from .fetch import FetchResult, fetch_and_extract
from .rerank import rerank, score_hit
from .semantic_scholar import SemanticScholarClient
from .structure import (
    LONG_SOURCE_TOKEN_THRESHOLD,
    build_structured_content,
    is_long_source,
    load_source_section,
    render_outline,
    rough_token_count,
)
from .unpaywall import UnpaywallClient

__all__ = [
    "LONG_SOURCE_TOKEN_THRESHOLD",
    "ArxivClient",
    "BraveClient",
    "BraveSearchError",
    "FetchResult",
    "RetrievalCache",
    "SearchHit",
    "SemanticScholarClient",
    "UnpaywallClient",
    "build_structured_content",
    "fetch_and_extract",
    "is_long_source",
    "load_source_section",
    "render_outline",
    "rerank",
    "rough_token_count",
    "score_hit",
    "search_academic",
]
