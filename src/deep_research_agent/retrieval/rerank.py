"""Lexical snippet reranker.

A cheap, deterministic rerank step between search and fetch: scores each
`SearchHit` by lexical overlap between its title/snippet and the query,
then returns hits sorted by score. The point is to drop obvious dreck
before we pay the fetch + tier-classify cost, not to replace semantic
relevance — an LLM reranker (or embeddings) would be better and lands
later.

Scoring:
  - Tokenize query and hit.title/snippet on non-alpha-numeric boundaries.
  - Lowercase, strip stopwords.
  - Score = weighted token overlap:
        title matches count 2x  (titles are short and load-bearing)
        snippet matches count 1x
  - Academic hits get a small base bonus (+1.0) so they're not ranked
    below SEO-optimized Brave titles that happen to share more tokens.

Returns the same list shape so callers can swap rerank in/out freely.
"""

from __future__ import annotations

import re

from .brave import SearchHit

_TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,}")

# Minimal stopword list — just the tokens most likely to inflate overlap
# without carrying meaning. Not a full NLP stopword set on purpose.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "of",
        "for",
        "in",
        "on",
        "to",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "with",
        "by",
        "from",
        "how",
        "what",
        "why",
        "do",
        "does",
        "did",
        "can",
        "will",
        "or",
        "but",
        "if",
        "as",
        "at",
        "about",
        "into",
        "over",
        "between",
    }
)

_ACADEMIC_SOURCES: frozenset[str] = frozenset({"semantic_scholar", "arxiv"})


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS}


def score_hit(hit: SearchHit, query_tokens: set[str]) -> float:
    title_matches = len(_tokens(hit.title) & query_tokens)
    snippet_matches = len(_tokens(hit.snippet) & query_tokens)
    base = 1.0 if hit.source in _ACADEMIC_SOURCES else 0.0
    return base + 2.0 * title_matches + snippet_matches


def rerank(hits: list[SearchHit], query: str) -> list[SearchHit]:
    """Return `hits` sorted by descending relevance score.

    Stable: ties preserve the caller's original order — useful when the
    caller has already put academic hits before web hits for dedup
    reasons. Returns a new list; does not mutate input.
    """
    q = _tokens(query)
    if not q:
        return list(hits)
    return sorted(hits, key=lambda h: score_hit(h, q), reverse=True)
