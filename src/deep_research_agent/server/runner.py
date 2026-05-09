"""Runs one research session and publishes events to a RunSession.

This is the server-side analogue of cli._run_research: same Scheduler,
same AgentExecutor, same register_handlers — the only difference is
that callbacks publish Events onto a session instead of printing to
the terminal.
"""

from __future__ import annotations

import contextvars
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import LocalConfig, RoutingConfig
from ..executor import AgentExecutor, register_handlers
from ..export import export_run
from ..replanner import run_replanner
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
from ..token_usage import TokenUsageTracker
from .events import (
    RunSession,
    event_note_created,
    event_note_replaced,
    event_replan_done,
    event_replan_started,
    event_run_done,
    event_run_failed,
    event_run_started,
    event_task_done,
    event_task_started,
)

logger = logging.getLogger(__name__)

# Per-run log file plumbing. Each run gets its own run.log in its
# run_dir, colocated with notes/, tasks.json, token_usage.json. We use
# a contextvar set at run_session entry and a filter keyed off it so
# concurrent runs don't cross-contaminate: every log record emitted
# from the same asyncio task chain carries that run's id, and each
# run's FileHandler only admits records matching its own id.
_RUN_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar("dra_run_id", default=None)

_RUN_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _RunIdFilter(logging.Filter):
    """Admit only records emitted under this run's contextvar value."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        return _RUN_ID_CTX.get() == self._run_id


def _attach_run_log_handler(run_dir: Path, run_id: str) -> logging.FileHandler:
    """Attach a FileHandler writing to run_dir/run.log for this run.

    Pinned at DEBUG unconditionally — the per-run log is a diagnostic
    artifact you look at only when something's wrong, so capturing
    every DEBUG line is the right default. Console verbosity is
    controlled separately by DRA_LOG_LEVEL (app.py:_configure_logging).
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(run_dir / "run.log", mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter(_RUN_LOG_FORMAT))
    fh.addFilter(_RunIdFilter(run_id))
    fh.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(fh)
    return fh


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
    _RUN_ID_CTX.set(session.run_id)
    run_log_handler = _attach_run_log_handler(run_dir, session.run_id)
    tracker = TokenUsageTracker()
    # Initialize graphs outside the try so the failure-path export can
    # read them even if setup itself raised.
    tg = TaskGraph()
    ng = NoteGraph()

    try:
        ex = AgentExecutor(routing=routing, local=local, tracker=tracker)
        register_handlers(ex)
        root_task = Task(
            id=new_task_id(),
            goal=session.query,
            type=TaskType.LANDSCAPE_SURVEY,
            role=RoleClass.GENERATIVE,
            tier=TaskTier.HIGH,
            success_criteria="produce a research report answering the query",
            created_at=datetime.now(UTC),
        )
        tg.add(root_task)

        def _on_task_start(task: Task) -> None:
            # Pass routing so the event carries the resolved model_id for
            # the UI to display on the agent card.
            session.publish(event_task_started(task, routing))

        def _on_task_done(task: Task, result: TaskResult) -> None:
            verdict = result.verdict or f"wrote {len(task.writes_notes)} note(s)"
            session.publish(event_task_done(task, verdict))

        def _on_note_mutation(mut: NoteMutation, task: Task | None) -> None:
            session.notes[mut.note.id] = mut.note
            if mut.kind == "create":
                session.publish(event_note_created(mut.note))
            else:
                session.publish(event_note_replaced(mut.note))

        replan_counter = {"n": 0}

        async def _replanner(task_graph: TaskGraph, note_graph: NoteGraph):
            # Emit synthetic task_started/task_done around each replan
            # cycle so the UI's Running Agents panel shows a card for
            # the replanner (which doesn't go through the normal task
            # dispatch path). The synth_id is ours to own — no entry
            # is added to the real task_graph.
            replan_counter["n"] += 1
            start_evt, synth_id = event_replan_started(replan_counter["n"], routing)
            session.publish(start_evt)
            try:
                result = await run_replanner(
                    task_graph,
                    note_graph,
                    routing,
                    local,
                    root_task.id,
                    tracker=tracker,
                )
            except Exception as exc:
                session.publish(
                    event_replan_done(
                        synth_id, f"replan failed: {type(exc).__name__}", failed=True
                    )
                )
                raise
            # Pull a short verdict from the decision_note returned
            # alongside the mutations — gives the history row actual
            # content instead of a bare "done".
            _mutations, decision_note = result
            verdict = (decision_note.description or "replan cycle complete")[:140]
            session.publish(event_replan_done(synth_id, verdict))
            return result

        sched = Scheduler(
            tg,
            ng,
            ex,
            on_task_start=_on_task_start,
            on_task_done=_on_task_done,
            on_note_mutation=_on_note_mutation,
            replanner=_replanner,
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
        # Export whatever state we have so a failed run is still
        # autopsy-able from disk (notes + tasks snapshot). Without
        # this, a stall/kill leaves nothing behind and the only
        # forensics come from the live log stream.
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            export_run(run_dir, ng, tg)
        except Exception:
            logger.exception("partial export failed run_id=%s", session.run_id)
        session.publish(event_run_failed(f"{type(exc).__name__}: {exc}"))
    finally:
        # Token usage + summary are always recorded — costs don't care
        # whether the run finished, and we want visibility into where
        # the tokens went on stalls.
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            tracker.save_json(run_dir / "token_usage.json")
        except Exception:
            logger.exception("token_usage save failed run_id=%s", session.run_id)
        logger.info("run_id=%s %s", session.run_id, tracker.format_table())
        # Detach the per-run file handler so it's not left hanging on
        # the root logger (memory leak across many runs) and so the
        # file descriptor closes.
        try:
            logging.getLogger().removeHandler(run_log_handler)
            run_log_handler.close()
        except Exception:
            logger.exception("run_log detach failed run_id=%s", session.run_id)
        session.finished = True
