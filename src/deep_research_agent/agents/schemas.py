"""Output schemas for agents and tools + report composition helper.

Kept deliberately small. The note graph (see `agents/memory.py`) is the
agents' working memory; these schemas are just the typed wrapper
around the *final answer* each agent returns to its caller. Source
tier / claims / quotes live on source notes, not in these payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..schemas.ids import NoteID

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
    confidence: str = Field(
        ...,
        description="One of: 'high', 'medium', 'low'. Reflect source quality + coverage.",
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


# --- Report composition ----------------------------------------------------


def compose_report_markdown(
    *,
    query: str,
    report: ResearcherReport | None,
    memory: NoteMemory | None = None,
) -> str:
    """Build a human-readable markdown report.

    Happy path: `report.report_markdown` is used verbatim, followed by
    a sources appendix from memory.

    Crash path: `report` is None. Reconstruct a partial report from
    answered QUESTION notes in memory so the run still produces some
    markdown on disk.
    """
    from ..schemas.enums import NoteType
    from ..schemas.note import QuestionMetadata, SourceNoteMetadata

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
            if isinstance(n.metadata, QuestionMetadata) and n.metadata.status == "SYNTHESIZED"
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

    # Sources appendix - always available from memory.
    if memory is not None:
        sources = memory.list_by_type(NoteType.SOURCE)
        if sources:
            parts.append("## Sources")
            parts.append("")
            for n in sources:
                meta = n.metadata
                if not isinstance(meta, SourceNoteMetadata):
                    continue
                tier_label = f"tier {meta.tier.value}" if meta.tier is not None else "not-tiered"
                pr = " - peer-reviewed" if meta.peer_reviewed else ""
                parts.append(f"- **[{n.id}]** [{meta.title}]({meta.url}) - {tier_label}{pr}")
                if meta.summary:
                    parts.append(f"  - {meta.summary}")
            parts.append("")

    return "\n".join(parts)
