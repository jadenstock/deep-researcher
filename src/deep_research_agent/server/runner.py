"""Runs one agent research session and publishes events to a RunSession.

Server-side analogue of cli._run: same top-level `research_run`, same
Deps, same note memory - the difference is that an `EventPublisher`
implementation (`SessionPublisher`) writes agent + note events onto a
`RunSession`, and the final report is materialized as a synthesis
note so the UI's /api/note/{run_id}/{note_id} endpoint can fetch it.
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..agents.deps import build_deps
from ..agents.events import EventPublisher
from ..agents.memory import NoteMemory, new_note_id
from ..agents.researcher import research_run
from ..agents.schemas import ResearcherReport, compose_report_markdown
from ..config import LocalConfig, RoutingConfig
from ..schemas.enums import NoteType
from ..schemas.ids import NoteID
from ..schemas.note import Note, SynthesisMetadata
from .events import (
    RunSession,
    event_agent_done,
    event_agent_started,
    event_note_created,
    event_note_replaced,
    event_run_done,
    event_run_failed,
    event_run_started,
    event_tool_call_end,
    event_tool_call_start,
)

logger = logging.getLogger(__name__)


# Per-run log file plumbing. Each run gets its own run.log in its
# run_dir. contextvar + filter keeps concurrent runs from cross-
# contaminating each other's logs.
_RUN_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar("dra_run_id", default=None)

_RUN_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _RunIdFilter(logging.Filter):
    """Admit only records emitted under this run's contextvar value."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        return _RUN_ID_CTX.get() == self._run_id


# Silence noisy third-party libraries once per process; their DEBUG
# streams drown real errors.
for _noisy in ("pdfminer", "pypdf", "httpcore", "httpx", "urllib3", "trafilatura"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _attach_run_log_handler(run_dir: Path, run_id: str) -> logging.FileHandler:
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(run_dir / "run.log", mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter(_RUN_LOG_FORMAT))
    fh.addFilter(_RunIdFilter(run_id))
    fh.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(fh)
    return fh


class SessionPublisher(EventPublisher):
    """EventPublisher that forwards agent + note events onto a RunSession.

    Implements the Deps.events protocol used by researcher.py,
    question_investigator.py, and NoteMemory. Keeps a back-reference
    to the session so the WebSocket handler can replay + stream every
    event for this run.
    """

    def __init__(self, session: RunSession) -> None:
        self._session = session

    def on_agent_start(
        self,
        *,
        agent_id: str,
        agent_type: str,
        goal: str,
        tier: str,
        role: str,
        model_id: str | None,
    ) -> None:
        self._session.publish(
            event_agent_started(
                agent_id=agent_id,
                agent_type=agent_type,
                goal=goal,
                tier=tier,
                role=role,
                model_id=model_id,
            )
        )

    def on_agent_done(
        self,
        *,
        agent_id: str,
        agent_type: str,
        status: str,
        verdict: str,
    ) -> None:
        self._session.publish(
            event_agent_done(
                agent_id=agent_id,
                agent_type=agent_type,
                status=status,
                verdict=verdict,
            )
        )

    def on_note_created(self, note: Note) -> None:
        self._session.notes[note.id] = note
        self._session.publish(event_note_created(note))

    def on_note_replaced(self, note: Note) -> None:
        self._session.notes[note.id] = note
        self._session.publish(event_note_replaced(note))

    def on_tool_start(
        self,
        *,
        agent_id: str,
        tool_call_id: str,
        tool: str,
        summary: str,
    ) -> None:
        self._session.publish(
            event_tool_call_start(
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                tool=tool,
                summary=summary,
            )
        )

    def on_tool_end(
        self,
        *,
        agent_id: str,
        tool_call_id: str,
        tool: str,
        status: str,
        summary: str,
        duration_ms: int,
    ) -> None:
        self._session.publish(
            event_tool_call_end(
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                tool=tool,
                status=status,
                summary=summary,
                duration_ms=duration_ms,
            )
        )


def _now() -> datetime:
    return datetime.now(UTC)


async def _materialize_report_note(
    session: RunSession,
    publisher: SessionPublisher,
    report_markdown: str,
    bottom_line: str,
    query: str,
) -> NoteID:
    """Create a synthesis_note containing the final report and publish
    it so the UI's note tab + report viewer both see it."""
    note_id = new_note_id("report")
    note = Note(
        id=note_id,
        type=NoteType.SYNTHESIS,
        title="Research report",
        description=bottom_line[:280],
        content=report_markdown,
        metadata=SynthesisMetadata(pattern="researcher"),
        last_modified_at=_now(),
        created_at=_now(),
    )
    # Publish directly - we're not going through NoteMemory because
    # the report lives conceptually outside agent memory (it's the
    # output, not working state). Routing it through the session keeps
    # the UI contract uniform.
    publisher.on_note_created(note)
    del query  # reserved for future metadata
    return note_id


def _build_report_markdown(
    query: str,
    report: ResearcherReport | None,
    memory: NoteMemory,
) -> str:
    """Compose the final report markdown.

    Happy path: ResearcherReport present; compose_report_markdown
    uses its fields (and report_markdown verbatim if the model filled
    it in).

    Crash path: report is None. compose_report_markdown falls back to
    the synthesis_notes in memory (each sub-agent persists its
    QuestionSynthesis as one) plus the source_notes appendix.
    """
    return compose_report_markdown(query=query, report=report, memory=memory)


def _dump_artifacts(
    run_dir: Path,
    query: str,
    notes: dict[str, Note],
    report_markdown: str | None,
    report_json: dict | None,
) -> None:
    """Persist per-run artifacts: report.md, report.json, notes.json."""
    run_dir.mkdir(parents=True, exist_ok=True)
    notes_out = [n.model_dump(mode="json") for n in notes.values()]
    (run_dir / "notes.json").write_text(json.dumps(notes_out, indent=2, default=str))
    if report_json is not None:
        (run_dir / "report.json").write_text(json.dumps(report_json, indent=2, default=str))
    if report_markdown is not None:
        md = f"# Research report\n\n**Query:** {query}\n\n{report_markdown}\n"
        (run_dir / "report.md").write_text(md)


async def run_session(
    session: RunSession,
    routing: RoutingConfig,
    local: LocalConfig,
    runs_dir: Path,
) -> None:
    """Execute one agent research run and stream events onto `session`.

    Any exception inside the run is caught and surfaced as a
    `run_failed` event rather than propagated - the WebSocket clients
    need to see the failure.
    """
    session.publish(event_run_started(session.run_id, session.query))
    run_dir = runs_dir / session.run_id
    _RUN_ID_CTX.set(session.run_id)
    run_log_handler = _attach_run_log_handler(run_dir, session.run_id)

    publisher = SessionPublisher(session)
    deps = build_deps(local, routing, events=publisher)

    try:
        report = await research_run(deps, session.query)
        # Happy path: the researcher called write_research_report,
        # which created the synthesis_note and stashed its ID under
        # `__report_note_id__`. Use that directly.
        report_note_id = deps.outputs.get("__report_note_id__")
        if not isinstance(report_note_id, str):
            # Agent ended without committing - fall back to composing
            # a report from the minimal ResearcherReport that
            # research_run fabricated.
            logger.warning(
                "run_id=%s: write_research_report never fired; "
                "materializing composed report from available notes",
                session.run_id,
            )
            fallback_md = _build_report_markdown(session.query, report, deps.memory)
            report_note_id = await _materialize_report_note(
                session=session,
                publisher=publisher,
                report_markdown=fallback_md,
                bottom_line=report.bottom_line,
                query=session.query,
            )

        _dump_artifacts(
            run_dir=run_dir,
            query=session.query,
            notes={n.id: n for n in deps.memory.all()},
            report_markdown=(
                report.report_markdown or _build_report_markdown(session.query, report, deps.memory)
            ),
            report_json=report.model_dump(mode="json"),
        )
        session.publish(event_run_done(report_note_id))
        # Count sub-question syntheses (written by investigators) vs
        # the top-level report synthesis for an accurate log line.
        sub_syntheses = [
            n
            for n in deps.memory.list_by_type(NoteType.SYNTHESIS)
            if isinstance(n.metadata, SynthesisMetadata)
            and n.metadata.pattern.startswith("investigator:")
        ]
        logger.info(
            "run complete run_id=%s notes=%d questions=%d",
            session.run_id,
            len(deps.memory),
            len(sub_syntheses),
        )
    except Exception as exc:
        logger.exception("run failed run_id=%s", session.run_id)
        # Dump whatever partial state we have so a failed run is
        # autopsy-able from disk. Every sub-agent persists its
        # QuestionSynthesis as a synthesis_note before returning, so
        # even when the top-level researcher crashes on its output we
        # can still compose a partial report from the note graph.
        try:
            partial_md = _build_report_markdown(session.query, None, deps.memory)
            _dump_artifacts(
                run_dir=run_dir,
                query=session.query,
                notes={n.id: n for n in deps.memory.all()},
                report_markdown=partial_md,
                report_json=None,
            )
            # Materialize a synthesis_note for the partial report so
            # the UI's report tab can still render something.
            partial_note_id = await _materialize_report_note(
                session=session,
                publisher=publisher,
                report_markdown=partial_md,
                bottom_line=(f"Partial report - run failed: {type(exc).__name__}"),
                query=session.query,
            )
            logger.info(
                "partial report materialized run_id=%s note=%s",
                session.run_id,
                partial_note_id,
            )
        except Exception:
            logger.exception("partial dump failed run_id=%s", session.run_id)
        session.publish(event_run_failed(f"{type(exc).__name__}: {exc}"))
    finally:
        # Token usage snapshot - costs don't care whether the run
        # finished. Stored as JSON next to the run artifacts.
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            deps.tracker.save_json(run_dir / "token_usage.json")
        except Exception:
            logger.exception("token_usage save failed run_id=%s", session.run_id)
        logger.info("run_id=%s %s", session.run_id, deps.tracker.format_table())
        try:
            logging.getLogger().removeHandler(run_log_handler)
            run_log_handler.close()
        except Exception:
            logger.exception("run_log detach failed run_id=%s", session.run_id)
        session.finished = True
