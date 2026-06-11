from __future__ import annotations

from datetime import UTC, datetime

from deep_research_agent.agents.schemas import (
    ReportRenderOptions,
    ResearcherReport,
    compose_report_markdown,
)
from deep_research_agent.schemas.enums import NoteType
from deep_research_agent.schemas.ids import NoteID
from deep_research_agent.schemas.note import Note, SourceNoteMetadata


class FakeMemory:
    def __init__(self, notes: list[Note]) -> None:
        self._notes = notes

    def list_by_type(self, note_type: NoteType) -> list[Note]:
        return [n for n in self._notes if n.type == note_type]


def _source_note(source_id: str, title: str, url: str, summary: str | None = None) -> Note:
    now = datetime.now(UTC)
    return Note(
        id=NoteID(source_id),
        type=NoteType.SOURCE,
        title=title,
        content="",
        metadata=SourceNoteMetadata(url=url, title=title, summary=summary),
        created_at=now,
        last_modified_at=now,
    )


def test_default_report_rendering_uses_numbered_linked_sources_and_all_bibliography() -> None:
    memory = FakeMemory(
        [
            _source_note("source-aaa111", "Alpha", "https://a.test", "Alpha summary."),
            _source_note("source-bbb222", "Beta", "https://b.test"),
            _source_note("source-ccc333", "Gamma", "https://c.test"),
        ]
    )
    report = ResearcherReport(
        query="q",
        report_markdown=(
            "One claim [source-bbb222, source-aaa111]. "
            "Repeated evidence [source-bbb222]."
        ),
    )

    rendered = compose_report_markdown(query="q", report=report, memory=memory)

    assert "[[Source 1](#source-1), [Source 2](#source-2)]" in rendered
    assert "[[Source 1](#source-1)]" in rendered
    assert "1. <a id=\"source-1\"></a>**Source 1:** [Beta](https://b.test)" in rendered
    assert "2. <a id=\"source-2\"></a>**Source 2:** [Alpha](https://a.test)" in rendered
    assert "3. <a id=\"source-3\"></a>**Source 3:** [Gamma](https://c.test)" in rendered
    assert "Alpha summary." in rendered


def test_report_rendering_can_disable_inline_links_and_limit_bibliography_to_inline() -> None:
    memory = FakeMemory(
        [
            _source_note("source-aaa111", "Alpha", "https://a.test"),
            _source_note("source-bbb222", "Beta", "https://b.test"),
        ]
    )
    report = ResearcherReport(
        query="q",
        report_markdown="One claim [source-aaa111].",
    )
    options = ReportRenderOptions(
        inline_reference_links=False,
        bibliography_source_scope="inline",
    )

    rendered = compose_report_markdown(
        query="q",
        report=report,
        memory=memory,
        render_options=options,
    )

    assert "One claim [Source 1]." in rendered
    assert "[Source 1](#source-1)" not in rendered
    assert "**Source 1:** [Alpha](https://a.test)" in rendered
    assert "Beta" not in rendered


def test_report_rendering_can_preserve_raw_note_id_labels() -> None:
    memory = FakeMemory([_source_note("source-aaa111", "Alpha", "https://a.test")])
    report = ResearcherReport(query="q", report_markdown="One claim [source-aaa111].")
    options = ReportRenderOptions(source_label_style="note_id")

    rendered = compose_report_markdown(
        query="q",
        report=report,
        memory=memory,
        render_options=options,
    )

    assert "[[source-aaa111](#source-1)]" in rendered
    assert "**source-aaa111:** [Alpha](https://a.test)" in rendered
