"""Runs one research session and publishes events to a RunSession.

This is the server-side analogue of cli._run_research: same Scheduler,
same AgentExecutor, same register_handlers — the only difference is
that callbacks publish Events onto a session instead of printing to
the terminal.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import LocalConfig, RoutingConfig
from ..executor import AgentExecutor, register_handlers
from ..export import export_run
from ..scheduler import (
    NoteGraph,
    NoteMutation,
    Scheduler,
    TaskGraph,
    TaskResult,
    new_task_id,
)
from ..schemas import Task
from ..schemas.enums import NoteType, RoleClass, TaskTier, TaskType
from .events import (
    RunSession,
    event_note_created,
    event_note_replaced,
    event_run_done,
    event_run_failed,
    event_run_started,
    event_task_done,
    event_task_started,
)

logger = logging.getLogger(__name__)


async def run_session(
    session: RunSession,
    routing: RoutingConfig,
    local: LocalConfig,
    runs_dir: Path,
) -> None:
    """Execute one research run and stream events onto `session`.

    Any exception inside the run is caught and surfaced as a
    `run_failed` event rather than propagated — the WebSocket clients
    need to see the failure.
    """
    session.publish(event_run_started(session.run_id, session.query))
    run_dir = runs_dir / session.run_id

    try:
        ex = AgentExecutor(routing=routing, local=local)
        register_handlers(ex)

        tg = TaskGraph()
        ng = NoteGraph()
        tg.add(
            Task(
                id=new_task_id(),
                goal=session.query,
                type=TaskType.LANDSCAPE_SURVEY,
                role=RoleClass.GENERATIVE,
                tier=TaskTier.HIGH,
                success_criteria="produce a research report answering the query",
                created_at=datetime.now(UTC),
            )
        )

        def _on_task_start(task: Task) -> None:
            session.publish(event_task_started(task))

        def _on_task_done(task: Task, result: TaskResult) -> None:
            verdict = result.verdict or f"wrote {len(task.writes_notes)} note(s)"
            session.publish(event_task_done(task, verdict))

        def _on_note_mutation(mut: NoteMutation, task: Task) -> None:
            session.notes[mut.note.id] = mut.note
            if mut.kind == "create":
                session.publish(event_note_created(mut.note))
            else:
                session.publish(event_note_replaced(mut.note))

        sched = Scheduler(
            tg,
            ng,
            ex,
            on_task_start=_on_task_start,
            on_task_done=_on_task_done,
            on_note_mutation=_on_note_mutation,
        )
        await sched.run()

        report_path = export_run(run_dir, ng, tg)
        report_note_id = next(
            (
                n.id
                for n in ng.all()
                if n.type == NoteType.DECISION and n.metadata.category == "final_report"
            ),
            None,
        )
        session.publish(event_run_done(report_note_id))
        logger.info(
            "run complete run_id=%s report=%s notes=%d tasks=%d",
            session.run_id,
            report_path,
            len(ng),
            len(tg),
        )
    except Exception as exc:
        logger.exception("run failed run_id=%s", session.run_id)
        session.publish(event_run_failed(f"{type(exc).__name__}: {exc}"))
    finally:
        session.finished = True
