"""Search + fetch + extract retrieval layer.

v0: Brave Search for web discovery; httpx + trafilatura for HTML fetch
and main-content extraction; diskcache for replay.

Academic sources (Semantic Scholar, arXiv) and PDF extraction
(markitdown) land in v2.
"""

from .brave import BraveClient, BraveSearchError, SearchHit
from .cache import RetrievalCache
from .fetch import FetchResult, fetch_and_extract

__all__ = [
    "BraveClient",
    "BraveSearchError",
    "FetchResult",
    "RetrievalCache",
    "SearchHit",
    "fetch_and_extract",
]
