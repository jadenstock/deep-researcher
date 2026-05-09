"""Corpus index: URL-keyed view over source_notes in the note graph.

CorpusIndex is intentionally stateless — it's a lookup layer built on
demand from the note graph. The source_notes themselves are the truth;
the index just makes common queries ergonomic (by_url, scouted_for_
question, unanalyzed_for_question).

URL canonicalization is deliberately conservative: we want two URLs that
point at the same content to collapse (http vs https, trailing slash, a
handful of tracking params), but we DO NOT try to identify semantic
duplicates across domains (arxiv.org/abs/X vs arxiv.org/pdf/X.pdf). The
rerank / relevance layers can de-prioritize near-duplicates; a strict
canonicalizer risks gluing distinct sources.
"""

from __future__ import annotations

from typing import cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..scheduler import NoteReader
from ..schemas import Note, NoteType, SourceState
from ..schemas.note import SourceNoteMetadata


def _src_meta(note: Note) -> SourceNoteMetadata:
    """Narrow the discriminated-union metadata to SourceNoteMetadata.

    Callers ensure `note.type == NoteType.SOURCE` before calling this —
    the narrow is purely for static analysis. At runtime the attribute
    access is identical.
    """
    return cast(SourceNoteMetadata, note.metadata)


# Tracking parameters to strip from URLs during canonicalization. Keeping
# the list small on purpose — we want two URLs that differ only in
# analytics junk to dedupe, not to strip parameters that actually change
# the response (page=N, id=X).
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "ref_url",
        "_ga",
        "_gl",
    }
)


def canonicalize_url(url: str) -> str:
    """Return a canonical form of `url` for corpus deduplication.

    Rules:
    - Scheme lowercased; http/https treated as equivalent (normalize to https).
    - Host lowercased; www. prefix dropped.
    - Tracking params in `_TRACKING_PARAMS` stripped; remaining params
      sorted for stable ordering.
    - Trailing slash on the path dropped (except when the path is just "/").
    - Fragment dropped — fragments are client-side anchors, never a
      different document.
    - Empty-string input returns "".
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip()
    scheme = parsed.scheme.lower() or "https"
    if scheme == "http":
        scheme = "https"
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # Preserve userinfo / port as-is (rare; don't mangle).
    path = parsed.path or ""
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    params.sort()
    query = urlencode(params)
    return urlunparse((scheme, host, path, parsed.params, query, ""))


class CorpusIndex:
    """Read-only view over source_notes in a NoteReader.

    Handlers construct this fresh each call — it's cheap, just iterates
    source_notes once. All queries return Notes (not raw metadata) so the
    caller can access id / version / links.

    Writes happen through the normal NoteMutation path — this class never
    mutates the note graph.
    """

    def __init__(self, notes: NoteReader) -> None:
        self._notes = notes
        self._sources: list[Note] = [n for n in notes.all() if n.type == NoteType.SOURCE]
        self._by_canonical: dict[str, Note] = {}
        for n in self._sources:
            key = canonicalize_url(_src_meta(n).url)
            # First write wins. Later sources with the same canonical URL
            # are an anomaly — log in callers, don't silently drop here.
            self._by_canonical.setdefault(key, n)

    # --- lookup ------------------------------------------------------------

    def by_url(self, url: str) -> Note | None:
        """Find a source_note by canonicalized URL."""
        return self._by_canonical.get(canonicalize_url(url))

    def all_sources(self) -> list[Note]:
        return list(self._sources)

    def by_state(self, state: SourceState) -> list[Note]:
        return [n for n in self._sources if _src_meta(n).state == state]

    # --- question-scoped views --------------------------------------------

    def relevant_to_question(
        self,
        question_note_id: str,
        *,
        min_relevance: float = 0.0,
        states: tuple[SourceState, ...] = (
            SourceState.FETCHED,
            SourceState.ANALYZED,
        ),
    ) -> list[Note]:
        """Sources with relevance ≥ `min_relevance` for a question, in any
        of the given states. Sorted by relevance descending.
        """
        out: list[tuple[float, Note]] = []
        for n in self._sources:
            meta = _src_meta(n)
            if meta.state not in states:
                continue
            score = meta.relevance.get(question_note_id, 0.0)
            if score >= min_relevance:
                out.append((score, n))
        out.sort(key=lambda p: p[0], reverse=True)
        return [n for _, n in out]

    def unanalyzed_for_question(
        self,
        question_note_id: str,
        *,
        min_relevance: float,
    ) -> list[Note]:
        """FETCHED/ANALYZED sources relevant to this question that haven't
        yet had ANALYZE_SOURCE run against them for this question. Drives
        the fan-out of analysis tasks.
        """
        out: list[tuple[float, Note]] = []
        for n in self._sources:
            meta = _src_meta(n)
            if meta.state not in (SourceState.FETCHED, SourceState.ANALYZED):
                continue
            if question_note_id in meta.analyzed_for:
                continue
            score = meta.relevance.get(question_note_id, 0.0)
            if score >= min_relevance:
                out.append((score, n))
        out.sort(key=lambda p: p[0], reverse=True)
        return [n for _, n in out]

    def analyzed_for_question(self, question_note_id: str) -> list[Note]:
        """Sources whose claims have been extracted for this question.
        Used by SYNTHESIZE to assemble the evidence digest.
        """
        return [n for n in self._sources if question_note_id in _src_meta(n).analyzed_for]

    # --- scouting-driven views --------------------------------------------

    def scouted_needing_relevance_scoring(self) -> list[Note]:
        """SCOUTED sources with no relevance scores yet. These are the
        input to RESCORE_RELEVANCE.
        """
        return [
            n
            for n in self._sources
            if _src_meta(n).state == SourceState.SCOUTED and not _src_meta(n).relevance
        ]

    def scouted_with_relevance(
        self,
        *,
        min_relevance: float,
    ) -> list[Note]:
        """SCOUTED sources with at least one question scoring ≥
        `min_relevance`. These are candidates for FETCH_AND_EXTRACT.
        """
        out: list[Note] = []
        for n in self._sources:
            meta = _src_meta(n)
            if meta.state != SourceState.SCOUTED:
                continue
            if not meta.relevance:
                continue
            if max(meta.relevance.values(), default=0.0) >= min_relevance:
                out.append(n)
        return out

    # --- stats -------------------------------------------------------------

    def coverage_summary(self) -> dict[str, int]:
        """Quick counts for logging / UI."""
        stats = {
            "total": len(self._sources),
            "scouted": 0,
            "fetched": 0,
            "analyzed": 0,
            "multi_question": 0,
        }
        for n in self._sources:
            meta = _src_meta(n)
            if meta.state == SourceState.SCOUTED:
                stats["scouted"] += 1
            elif meta.state == SourceState.FETCHED:
                stats["fetched"] += 1
            elif meta.state == SourceState.ANALYZED:
                stats["analyzed"] += 1
            if len(meta.analyzed_for) > 1:
                stats["multi_question"] += 1
        return stats
