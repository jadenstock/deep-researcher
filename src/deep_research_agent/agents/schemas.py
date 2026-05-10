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
    bottom_line: str = Field(
        ...,
        description="One- or two-sentence plain-English answer to the question.",
    )
    synthesis: str = Field(
        ...,
        description=(
            "Full markdown write-up. Multi-paragraph; cite source notes "
            "inline by their NoteID in brackets, e.g. [source-abc123]."
        ),
    )
    sources_cited: list[NoteID] = Field(
        default_factory=list,
        description="Source notes whose claims feed this synthesis.",
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


class ResearcherReport(BaseModel):
    """Final output of the top-level `researcher` agent.

    `report_markdown` is optional because it's a long-form field that
    models sometimes omit on the final structured output. When missing,
    callers compose a fallback from `bottom_line` +
    `cross_cutting_synthesis` + the per-question syntheses - the
    research itself isn't lost, only the narrative layering.
    """

    query: str
    bottom_line: str = Field(
        ...,
        description="2-4 sentence executive answer to the overall query.",
    )
    cross_cutting_synthesis: str = Field(
        default="",
        description=(
            "Short synthesis (1-3 paragraphs) of themes that emerge "
            "ACROSS the sub-questions - NOT a restatement of each. "
            "Leave empty only if the sub-questions are truly independent."
        ),
    )
    report_markdown: str = Field(
        default="",
        description=(
            "Optional: a full markdown report you've composed. If you "
            "leave this empty, we'll compose the final report from "
            "bottom_line + cross_cutting_synthesis + the per-question "
            "syntheses automatically. Prefer filling this in ONLY when "
            "you want a specific structure beyond the default; "
            "otherwise save the tokens and leave it empty."
        ),
    )
    questions_investigated: list[QuestionSynthesis] = Field(
        default_factory=list,
        description="Per-question syntheses the report is composed from.",
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

    If `report` is present and its `report_markdown` is non-empty, use
    it verbatim. Otherwise synthesize one from the structured parts:
    bottom_line + cross_cutting_synthesis + per-question syntheses +
    limitations, plus a sources appendix.

    If `report` is None (researcher crashed before producing output),
    fall back to the note graph: pull every synthesis_note as a
    per-question section, every source_note as the sources appendix.
    Result is always *some* markdown - runs should never produce an
    empty report.md on disk.
    """
    from ..schemas.enums import NoteType
    from ..schemas.note import QuestionMetadata, SourceNoteMetadata

    parts: list[str] = ["# Research report", "", f"**Query:** {query}", ""]

    if report is not None and report.report_markdown.strip():
        parts.append(report.report_markdown)
        parts.append("")
    else:
        if report is not None:
            parts.append("## Bottom line")
            parts.append("")
            parts.append(report.bottom_line)
            parts.append("")
            if report.cross_cutting_synthesis.strip():
                parts.append("## Cross-cutting synthesis")
                parts.append("")
                parts.append(report.cross_cutting_synthesis)
                parts.append("")
            if report.questions_investigated:
                parts.append("## Sub-question syntheses")
                parts.append("")
                for qs in report.questions_investigated:
                    parts.append(f"### {qs.question}")
                    parts.append("")
                    parts.append(f"**Bottom line:** {qs.bottom_line}")
                    parts.append("")
                    parts.append(f"**Confidence:** {qs.confidence}")
                    parts.append("")
                    parts.append(qs.synthesis)
                    parts.append("")
                    if qs.disagreements:
                        parts.append("**Disagreements:**")
                        for d in qs.disagreements:
                            parts.append(f"- {d}")
                        parts.append("")
                    if qs.open_issues:
                        parts.append("**Open issues:**")
                        for o in qs.open_issues:
                            parts.append(f"- {o}")
                        parts.append("")
            if report.limitations:
                parts.append("## Limitations")
                parts.append("")
                for lim in report.limitations:
                    parts.append(f"- {lim}")
                parts.append("")
        elif memory is not None:
            # No report at all - reconstruct from answered QUESTION notes.
            from ..schemas.note import QuestionMetadata

            answered = [
                n
                for n in memory.list_by_type(NoteType.QUESTION)
                if isinstance(n.metadata, QuestionMetadata) and n.metadata.status == "SYNTHESIZED"
            ]
            if answered:
                parts.append("## Partial report (reconstructed from answered questions)")
                parts.append("")
                parts.append(
                    "_The top-level researcher did not produce a final "
                    "structured report. The sub-question answers below "
                    "were recovered from the note graph._"
                )
                parts.append("")
                for n in answered:
                    meta = n.metadata
                    assert isinstance(meta, QuestionMetadata)
                    parts.append(f"### {n.description or n.title}")
                    parts.append("")
                    if meta.bottom_line:
                        parts.append(f"**Bottom line:** {meta.bottom_line}")
                        parts.append("")
                    if meta.synthesis_markdown:
                        parts.append(meta.synthesis_markdown)
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
