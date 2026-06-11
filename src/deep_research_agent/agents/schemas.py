"""Output schemas for agents and tools + report composition helper.

Kept deliberately small. The note graph (see `agents/memory.py`) is the
agents' working memory; these schemas are just the typed wrapper
around the *final answer* each agent returns to its caller. Source
tier / claims / quotes live on source notes, not in these payloads.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..schemas.enums import ConfidenceLevel, QuestionStatus
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata

if TYPE_CHECKING:
    from .memory import NoteMemory


class SearchResult(BaseModel):
    """Flattened SearchHit for tool returns.

    We don't reuse `retrieval.brave.SearchHit` directly because
    pydantic-ai serializes tool returns into the model context; a
    smaller shape keeps that context tight. Academic metadata
    (authors/venue/year) is included because it informs tier
    classification reasoning.
    """

    title: str
    url: str
    snippet: str
    source: str  # provider name: "brave" | "semantic_scholar" | "arxiv"
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    citation_count: int | None = None
    # Fallback URL when the primary `url` is an HTML landing page that
    # may return abstract-only content. Academic providers populate this;
    # scouts should forward it into create_source_note so scout_fetch can
    # fall back to the PDF.
    pdf_url: str | None = None
    # DOI, when the provider supplied one. Needed for S2 citation /
    # reference traversal via find_related_papers.
    doi: str | None = None


class FetchedContent(BaseModel):
    """Return value of the `fetch_url` tool."""

    url: str
    final_url: str
    status_code: int
    title: str | None = None
    markdown: str | None = None
    byte_length: int = 0
    truncated: bool = False  # true if markdown was cut for length
    reason: str | None = None  # populated when markdown is None


class QuestionSynthesis(BaseModel):
    """Final output of the `investigate_question` sub-agent."""

    question: str
    report: str = Field(
        ...,
        description=(
            "Full markdown write-up answering the question. "
            "Multi-paragraph; cite source notes inline by their NoteID "
            "in brackets, e.g. [source-abc123]."
        ),
    )
    sources_cited: list[NoteID] = Field(
        default_factory=list,
        description="Source notes whose claims feed this report.",
    )
    disagreements: list[str] = Field(
        default_factory=list,
        description=(
            "Points where sources disagree or where the evidence is "
            "genuinely mixed. Empty if findings converge."
        ),
    )
    open_issues: list[str] = Field(
        default_factory=list,
        description=(
            "Things you couldn't answer - bad coverage, paywalls, "
            "contradicting claims that need a tiebreaker source."
        ),
    )
    confidence: ConfidenceLevel = Field(
        ...,
        description="One of: 'high', 'medium', 'low'. Reflect source quality + coverage.",
    )


def question_synthesis_from_note(note: Note) -> QuestionSynthesis | None:
    """Reconstruct a QuestionSynthesis from a SYNTHESIZED QUESTION note.

    Returns None if the note isn't a QUESTION note or hasn't been
    answered yet (status != SYNTHESIZED). Callers use the None return
    to trigger a fallback `QuestionSynthesis` with low confidence.
    """
    meta = note.metadata
    if not isinstance(meta, QuestionMetadata):
        return None
    if meta.status != QuestionStatus.SYNTHESIZED:
        return None
    return QuestionSynthesis(
        question=note.description or note.title,
        report=meta.report_markdown or "",
        confidence=meta.confidence or ConfidenceLevel.LOW,
        sources_cited=list(meta.sources_cited),
        disagreements=list(meta.disagreements),
        open_issues=list(meta.open_issues),
    )


class ScoutedSource(BaseModel):
    """One entry in a scout's returned sourcelist.

    The scout creates a SCOUTED source note for the URL and may have
    called `scout_fetch` on it (in which case `preview` is non-empty and
    the source note's `content` holds the cleaned page text for the
    analyst to load via `load_note`). `tier_guess` / `relevance_guess`
    are first-pass judgments - the analyst re-rates on deep-read.
    """

    source_id: NoteID
    url: str
    title: str
    tier_guess: int | None = Field(
        None, description="Scout's first-pass tier (1..5), or None if not yet assessed."
    )
    relevance_guess: str = Field(
        "medium",
        description="Scout's relevance rating for the request: 'high' | 'medium' | 'low'.",
    )
    preview: str = Field(
        "",
        description=(
            "2-3 sentence excerpt from the scout's skim of the source content. "
            "Empty if the scout could not fetch (paywall, 404, etc.)."
        ),
    )


class ScoutResult(BaseModel):
    """Final output of a scout sub-agent dispatch."""

    sources: list[ScoutedSource] = Field(default_factory=list)
    coverage_note: str = Field(
        "",
        description=(
            "One-paragraph summary of what the scout searched, what it found, "
            "and where the coverage is thin or strong. Tells the analyst "
            "whether another scout dispatch on a different angle is warranted."
        ),
    )


class ResearcherReport(BaseModel):
    """Final output of the top-level `researcher` agent."""

    query: str
    report_markdown: str = Field(
        ...,
        description="The full markdown report answering the overall query.",
    )
    questions_investigated: list[QuestionSynthesis] = Field(
        default_factory=list,
        description="Per-question reports that fed into the final report.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="What the report could not cover or where confidence is low.",
    )


class ReportRenderOptions(BaseModel):
    """Presentation options for the human-readable markdown artifact."""

    inline_reference_links: bool = Field(
        True,
        description="When true, inline source labels link to the bibliography entry.",
    )
    bibliography_source_scope: str = Field(
        "all",
        description=(
            "'all' includes every source note; 'inline' includes only inline-cited sources."
        ),
    )
    source_label_style: str = Field(
        "numbered",
        description="'numbered' renders Source 1/2; 'note_id' preserves raw source note ids.",
    )

    def normalized(self) -> ReportRenderOptions:
        scope = self.bibliography_source_scope
        if scope not in {"all", "inline"}:
            scope = "all"
        style = self.source_label_style.replace("-", "_")
        if style not in {"numbered", "note_id"}:
            style = "numbered"
        return self.model_copy(
            update={
                "bibliography_source_scope": scope,
                "source_label_style": style,
            }
        )


# --- Report composition ----------------------------------------------------


_SOURCE_REF_RE = re.compile(r"\[(source-[A-Za-z0-9]+(?:\s*,\s*source-[A-Za-z0-9]+)*)\]")


def _source_ids_in_markdown(markdown: str) -> list[NoteID]:
    seen: set[str] = set()
    ordered: list[NoteID] = []
    for match in _SOURCE_REF_RE.finditer(markdown):
        for part in match.group(1).split(","):
            source_id = part.strip()
            if source_id not in seen:
                seen.add(source_id)
                ordered.append(NoteID(source_id))
    return ordered


def _source_label(source_id: NoteID, number: int, options: ReportRenderOptions) -> str:
    if options.source_label_style == "note_id":
        return str(source_id)
    return f"Source {number}"


def _replace_inline_source_refs(
    markdown: str,
    *,
    numbers_by_source_id: dict[NoteID, int],
    options: ReportRenderOptions,
) -> str:
    def repl(match: re.Match[str]) -> str:
        labels: list[str] = []
        for part in match.group(1).split(","):
            source_id = NoteID(part.strip())
            number = numbers_by_source_id[source_id]
            label = _source_label(source_id, number, options)
            if options.inline_reference_links:
                labels.append(f"[{label}](#source-{number})")
            else:
                labels.append(label)
        return f"[{', '.join(labels)}]"

    return _SOURCE_REF_RE.sub(repl, markdown)


def _md_escape(text: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", text)


def compose_report_markdown(
    *,
    query: str,
    report: ResearcherReport | None,
    memory: NoteMemory | None = None,
    render_options: ReportRenderOptions | None = None,
) -> str:
    """Build a human-readable markdown report.

    Happy path: `report.report_markdown` is used verbatim, followed by
    a sources appendix from memory.

    Crash path: `report` is None. Reconstruct a partial report from
    answered QUESTION notes in memory so the run still produces some
    markdown on disk.
    """
    from ..schemas.enums import NoteType, QuestionStatus
    from ..schemas.note import QuestionMetadata, SourceNoteMetadata

    options = (render_options or ReportRenderOptions()).normalized()
    parts: list[str] = ["# Research report", "", f"**Query:** {query}", ""]

    if report is not None and report.report_markdown.strip():
        parts.append(report.report_markdown)
        parts.append("")
        if report.limitations:
            parts.append("## Limitations")
            parts.append("")
            for lim in report.limitations:
                parts.append(f"- {lim}")
            parts.append("")
    elif memory is not None:
        answered = [
            n
            for n in memory.list_by_type(NoteType.QUESTION)
            if isinstance(n.metadata, QuestionMetadata)
            and n.metadata.status == QuestionStatus.SYNTHESIZED
        ]
        if answered:
            parts.append("## Partial report (reconstructed from answered questions)")
            parts.append("")
            parts.append(
                "_The top-level researcher did not commit a final report. "
                "The sub-question answers below were recovered from the "
                "note graph._"
            )
            parts.append("")
            for n in answered:
                meta = n.metadata
                assert isinstance(meta, QuestionMetadata)
                parts.append(f"### {n.description or n.title}")
                parts.append("")
                if meta.report_markdown:
                    parts.append(meta.report_markdown)
                    parts.append("")
        else:
            parts.append("_No answered questions in memory._")
            parts.append("")

    body_markdown = "\n".join(parts)
    inline_source_ids = _source_ids_in_markdown(body_markdown)
    numbers_by_source_id = {source_id: i + 1 for i, source_id in enumerate(inline_source_ids)}
    body_markdown = _replace_inline_source_refs(
        body_markdown,
        numbers_by_source_id=numbers_by_source_id,
        options=options,
    )

    parts = [body_markdown]

    # Sources appendix - available from memory on normal and crash paths.
    if memory is not None:
        source_notes = memory.list_by_type(NoteType.SOURCE)
        source_by_id = {n.id: n for n in source_notes}
        bibliography_source_ids = list(inline_source_ids)
        if options.bibliography_source_scope == "all":
            seen = set(bibliography_source_ids)
            for n in source_notes:
                if n.id not in seen:
                    seen.add(n.id)
                    bibliography_source_ids.append(n.id)

        if bibliography_source_ids:
            parts.append("## Sources")
            parts.append("")
            for source_id in bibliography_source_ids:
                if source_id not in numbers_by_source_id:
                    numbers_by_source_id[source_id] = len(numbers_by_source_id) + 1
                source_num = numbers_by_source_id[source_id]
                anchor = f'<a id="source-{source_num}"></a>'
                n = source_by_id.get(source_id)
                if n is None:
                    label = _source_label(source_id, source_num, options)
                    parts.append(f"{source_num}. {anchor}**{label}:** `{source_id}` *(not found)*")
                    continue

                meta = n.metadata
                if not isinstance(meta, SourceNoteMetadata):
                    continue
                tier_label = f"tier {meta.tier.value}" if meta.tier is not None else "not-tiered"
                pr = " - peer-reviewed" if meta.peer_reviewed else ""
                label = _source_label(source_id, source_num, options)
                title = _md_escape(meta.title or n.title or str(source_id))
                title_md = f"[{title}]({meta.url})" if meta.url else title
                parts.append(
                    f"{source_num}. {anchor}**{label}:** {title_md} - {tier_label}{pr}"
                )
                if meta.summary:
                    parts.append(f"  - {meta.summary}")
            parts.append("")

    return "\n".join(parts)
