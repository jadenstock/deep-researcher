"""Retrieval clients used by the agent tool layer.

Only what the agent tools wrap is re-exported. Each client is a thin
async wrapper around one external provider:

- BraveClient - web search
- SemanticScholarClient - academic metadata + abstracts
- ArxivClient - preprint search
- fetch_and_extract - URL → markdown (HTML via trafilatura, PDF via MarkItDown)
"""

from .arxiv import ArxivClient
from .brave import BraveClient, BraveSearchError, SearchHit
from .fetch import FetchResult, fetch_and_extract
from .semantic_scholar import SemanticScholarClient

__all__ = [
    "ArxivClient",
    "BraveClient",
    "BraveSearchError",
    "FetchResult",
    "SearchHit",
    "SemanticScholarClient",
    "fetch_and_extract",
]
