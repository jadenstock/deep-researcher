"""Search + fetch + extract.

Serper for web search, Semantic Scholar for academic, arXiv direct for
AI/ML recency, Unpaywall for DOI → OA PDF resolution. Fetch uses httpx;
HTML → markdown via trafilatura; PDF → markdown via markitdown. Results
cached on disk keyed on `(tool, args_hash, day_bucket)` so a replay run
can proceed without network.
"""
