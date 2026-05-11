"""Runs one agent research session and publishes events to a RunSession.

Server-side analogue of cli._run: same top-level `research_run`, same
Deps, same note memory - the difference is that an `EventPublisher`
implementation (`SessionPublisher`) writes agent + note events onto a
`RunSession`. The final report lives on the root QUESTION note (the
one created by `research_run` for the user's query, transitioned to
status=SYNTHESIZED once the researcher calls `answer_question` on
it). The UI's /api/note/{run_id}/{note_id} endpoint fetches that
QUESTION note's content as the report.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from pathlib import Path

from .._time import utc_now
from ..agents.deps import build_deps, close_deps
from ..agents.events import EventPublisher
from ..agents.memory import NoteMemory, new_note_id
from ..agents.researcher import research_run
from ..agents.run_config import RunConfig
from ..agents.schemas import compose_report_markdown
from ..config import LocalConfig, RoutingConfig
from ..observability import silence_noisy_loggers
from ..run_artifacts import persist_run_artifacts
from ..schemas.enums import NoteType, QuestionStatus
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata, SynthesisMetadata
from .events import (
    RunSession,
    event_agent_done,
    event_agent_started,
    event_note_created,
    event_note_replaced,
    event_run_done,
    event_run_failed,
    event_run_started,
    event_token_usage,
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


silence_noisy_loggers()


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
    analyst.py, and NoteMemory. Keeps a back-reference
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
        mode: str | None = None,
    ) -> None:
        self._session.publish(
            event_agent_started(
                agent_id=agent_id,
                agent_type=agent_type,
                goal=goal,
                tier=tier,
                role=role,
                model_id=model_id,
                mode=mode,
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

    def on_token_usage(
        self,
        *,
        agent_id: str,
        agent_type: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None:
        self._session.publish(
            event_token_usage(
                agent_id=agent_id,
                agent_type=agent_type,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
        )


def _find_answered_root_question_id(memory: NoteMemory) -> NoteID | None:
    """Return the id of the root QUESTION note if it was answered.

    The root is the QUESTION note with no parent. "Answered" means
    status=SYNTHESIZED (the researcher called `answer_question` on it).
    After Phase E this note IS the final report - its `content` holds
    the synthesis markdown.
    """
    for n in memory.list_by_type(NoteType.QUESTION):
        meta = n.metadata
        if not isinstance(meta, QuestionMetadata):
            continue
        if meta.parent_question_id is None and meta.status == QuestionStatus.SYNTHESIZED:
            return n.id
    return None


async def _materialize_fallback_report_note(
    publisher: SessionPublisher,
    report_markdown: str,
    description: str,
) -> NoteID:
    """Compat shim: create a SYNTHESIS note holding a fallback report.

    Used only when the researcher ended without calling
    `answer_question` on the root question (so the root note has no
    report content to surface) or when the run crashed. The UI's
    report tab fetches whatever note id we emit in `run_done`, so we
    still need *some* note to point at. A SYNTHESIS note is fine here
    as a fallback sink; the happy-path report lives on the root
    QUESTION note.
    """
    note_id = new_note_id("report")
    note = Note(
        id=note_id,
        type=NoteType.SYNTHESIS,
        title="Research report (fallback)",
        description=description[:280],
        content=report_markdown,
        metadata=SynthesisMetadata(pattern="researcher"),
        last_modified_at=utc_now(),
        created_at=utc_now(),
    )
    # Publish directly - we're not going through NoteMemory because
    # this is a fallback artifact, not agent working state. Routing it
    # through the session keeps the UI contract uniform.
    publisher.on_note_created(note)
    return note_id


async def run_session(
    session: RunSession,
    routing: RoutingConfig,
    local: LocalConfig,
    runs_dir: Path,
    run_config: RunConfig | None = None,
) -> None:
    """Execute one agent research run and stream events onto `session`.

    Any exception inside the run is caught and surfaced as a
    `run_failed` event rather than propagated - the WebSocket clients
    need to see the failure.

    `run_config` carries UI-supplied knobs (budgets + model
    overrides). Defaults are used when omitted.
    """
    session.publish(event_run_started(session.run_id, session.query))
    run_dir = runs_dir / session.run_id
    _RUN_ID_CTX.set(session.run_id)
    run_log_handler = _attach_run_log_handler(run_dir, session.run_id)

    publisher = SessionPublisher(session)
    deps = build_deps(local, routing, events=publisher, run_config=run_config)
    session.tracker = deps.tracker

    try:
        report = await research_run(deps, session.query)
        # Happy path: the researcher called `answer_question` on the
        # root question note, which transitioned it to SYNTHESIZED and
        # wrote the final synthesis into its `content`. The root
        # QUESTION note IS the report note - surface its id to the UI.
        report_note_id: NoteID | None = _find_answered_root_question_id(deps.memory)
        if report_note_id is None:
            # Agent ended without committing to the root question -
            # fall back to composing a report from whatever state
            # research_run was able to assemble, and materialize it as
            # a SYNTHESIS note so the UI still has something to load.
            logger.warning(
                "run_id=%s: root question never answered; "
                "materializing composed report from available notes",
                session.run_id,
            )
            fallback_md = compose_report_markdown(
                query=session.query, report=report, memory=deps.memory
            )
            report_note_id = await _materialize_fallback_report_note(
                publisher=publisher,
                report_markdown=fallback_md,
                description=f"Fallback report for: {session.query}",
            )

        final_md = compose_report_markdown(query=session.query, report=report, memory=deps.memory)
        await persist_run_artifacts(
            run_dir,
            notes=deps.memory.all(),
            report_markdown=final_md,
            report_json=report.model_dump(mode="json"),
        )
        session.report_note_id = report_note_id
        session.publish(event_run_done(report_note_id))
        # Count answered sub-question notes for an accurate log line.
        answered_subs = [
            n
            for n in deps.memory.list_by_type(NoteType.QUESTION)
            if isinstance(n.metadata, QuestionMetadata)
            and n.metadata.status == QuestionStatus.SYNTHESIZED
            and n.metadata.parent_question_id is not None
        ]
        logger.info(
            "run complete run_id=%s notes=%d questions=%d",
            session.run_id,
            len(deps.memory),
            len(answered_subs),
        )
    except Exception as exc:
        logger.exception("run failed run_id=%s", session.run_id)
        # Compose a partial report from whatever SYNTHESIZED sub-question
        # notes survive so a failed run is still autopsy-able from disk.
        try:
            partial_md = compose_report_markdown(
                query=session.query, report=None, memory=deps.memory
            )
            await persist_run_artifacts(
                run_dir,
                notes=deps.memory.all(),
                report_markdown=partial_md,
                report_json=None,
            )
            partial_note_id = await _materialize_fallback_report_note(
                publisher=publisher,
                report_markdown=partial_md,
                description=f"Partial report - run failed: {type(exc).__name__}",
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
        # Token usage snapshot - costs don't care whether the run finished.
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(deps.tracker.save_json, run_dir / "token_usage.json")
        except Exception:
            logger.exception("token_usage save failed run_id=%s", session.run_id)
        logger.info("run_id=%s %s", session.run_id, deps.tracker.format_table())
        try:
            await close_deps(deps)
        except Exception:
            logger.exception("close_deps failed run_id=%s", session.run_id)
        try:
            logging.getLogger().removeHandler(run_log_handler)
            run_log_handler.close()
        except Exception:
            logger.exception("run_log detach failed run_id=%s", session.run_id)
        session.finished_at = utc_now()
        session.finished = True
