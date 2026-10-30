"""FastAPI app - starts runs, streams events over WebSocket.

Endpoints:
  POST /api/run            -> { run_id }, spawns the run in the background.
  WS   /api/ws/{run_id}    -> streams events; replays history on connect.
  GET  /api/note/{run_id}/{note_id} -> full Note JSON (content + metadata).
  GET  /                   -> the live UI (single-page static HTML).

One uvicorn process serves both the API and the frontend; the frontend
is a single static file under server/static/.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.chat import chat_default_model_id
from ..agents.run_config import RunConfig, defaults_payload
from ..agents.schemas import ReportRenderOptions
from ..config import (
    LocalConfig,
    RoutingConfig,
    load_local_config,
    load_routing_config,
)
from ..retrieval import apply_retrieval_rate_limits
from ..run_artifacts import summarize_notes
from ..run_id import new_run_id
from . import history
from .chat import ChatRegistry, hydrate_chat_session, run_chat_turn
from .events import SessionRegistry
from .report_filename import suggest_report_filename
from .runner import run_session

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_logging() -> None:
    """Set up split-level logging: clean console, verbose per-run files.

    The root logger runs at DEBUG so DEBUG records can flow through to
    handlers. Each handler caps its own level:
      - Console (stderr): DRA_LOG_LEVEL (default INFO).
      - Per-run FileHandler (attached by runner.py): DEBUG always.
      - Optional DRA_LOG_FILE FileHandler: DRA_LOG_LEVEL.

    DRA_LOG_LEVEL controls the *console* level only. Set it to DEBUG if
    you want debug lines on stderr too.
    """
    console_level_name = os.environ.get("DRA_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_LOG_FORMAT))
        console.setLevel(console_level)
        root.addHandler(console)
    else:
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(console_level)

    log_file = os.environ.get("DRA_LOG_FILE")
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        already_attached = any(
            isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path.resolve()
            for h in root.handlers
        )
        if not already_attached:
            fh = logging.FileHandler(path, mode="a", encoding="utf-8")
            fh.setFormatter(logging.Formatter(_LOG_FORMAT))
            fh.setLevel(console_level)
            root.addHandler(fh)
            root.info("log_file_attached path=%s level=%s", path, console_level_name)

    logging.getLogger("deep_research_agent").setLevel(logging.DEBUG)


_configure_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class RunRequest(BaseModel):
    query: str
    # Optional per-run knobs from the UI's Settings panel. Missing or
    # partial `config` falls through to `RunConfig` defaults, so older
    # clients that omit the field keep working unchanged.
    config: dict | None = None


class ChatMessageRequest(BaseModel):
    mode: str = "ask"
    content: str
    # Optional per-message model override; when None, falls back to
    # the routing config's GENERATIVE/MID default. Validated only at
    # the LiteLLM router on first use, so any string the catalog
    # exposes works.
    model_id: str | None = None


@dataclass(frozen=True)
class ServerState:
    """Holds the configs + registry for the lifetime of the server."""

    routing: RoutingConfig
    local: LocalConfig
    runs_dir: Path
    registry: SessionRegistry
    chat_registry: ChatRegistry


def create_app(
    routing_path: Path | str = "config/routing_lean.yaml",
    local_path: Path | str = "config/local.toml",
    runs_dir: Path | str = "runs",
) -> FastAPI:
    """Build and return a configured FastAPI app."""
    local = load_local_config(local_path)
    routing = load_routing_config(routing_path)
    apply_retrieval_rate_limits(local.retrieval)

    state = ServerState(
        routing=routing,
        local=local,
        runs_dir=Path(runs_dir),
        registry=SessionRegistry(),
        chat_registry=ChatRegistry(),
    )

    app = FastAPI(title="deep-research-agent live UI")

    @app.get("/")
    async def index() -> FileResponse:
        if not INDEX_HTML.exists():
            raise HTTPException(status_code=500, detail="index.html missing")
        # Force the browser to fetch fresh HTML on every page load. The
        # UI is iterated on frequently and stale JS gets blamed on the
        # backend more than once - easier to pay the reload cost.
        return FileResponse(
            INDEX_HTML,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.post("/api/run")
    async def start_run(body: RunRequest) -> dict[str, str]:
        if not body.query.strip():
            raise HTTPException(status_code=400, detail="query must not be empty")
        run_id = new_run_id()
        session = state.registry.create(run_id, body.query)
        run_config = RunConfig.from_payload(body.config)
        session.task = asyncio.create_task(
            run_session(
                session,
                state.routing,
                state.local,
                state.runs_dir,
                run_config=run_config,
            )
        )
        logger.info(
            "run queued run_id=%s query=%r cfg=%s",
            run_id,
            body.query[:160],
            {
                "analyst_budget": run_config.analyst_budget,
                "scout_budget_per_analyst": run_config.scout_budget_per_analyst,
                "scout_search_budget": run_config.scout_search_budget,
                "model_overrides": {
                    f"{tier.value}.{role.value}": model
                    for (tier, role), model in run_config.model_overrides.items()
                },
                "skip_landscape": run_config.skip_landscape,
                "report_render_options": run_config.report_render_options.model_dump(),
            },
        )
        return {"run_id": run_id}

    @app.get("/api/config/defaults")
    async def get_config_defaults() -> dict:
        """Return the tunable-knob defaults + slider ranges + model catalog.

        The UI's Settings panel fetches this on load to populate its
        sliders and dropdowns. Keeps the UI from hardcoding any
        default; the server stays the single source of truth.
        """
        return defaults_payload(state.routing)

    @app.get("/api/runs")
    async def list_runs() -> dict[str, list[dict]]:
        return {
            "runs": [
                {
                    "run_id": s.run_id,
                    "query": s.query,
                    "started_at": s.started_at.isoformat(),
                    "finished": s.finished,
                }
                for s in state.registry.all()
            ]
        }

    @app.get("/api/history")
    async def list_history() -> dict[str, list[dict]]:
        """Completed runs persisted under runs_dir, newest first."""
        runs = await asyncio.to_thread(history.list_history, state.runs_dir)
        return {"runs": runs}

    @app.get("/api/history/{run_id}/notes")
    async def history_notes(run_id: str) -> list[dict]:
        notes = await asyncio.to_thread(history.read_notes, state.runs_dir, run_id)
        if notes is None:
            raise HTTPException(status_code=404, detail="run not found")
        return notes

    @app.get("/api/history/{run_id}/report", response_class=PlainTextResponse)
    async def history_report(
        run_id: str,
        inline_reference_links: bool = True,
        bibliography: str = "inline",
        source_label_style: str = "numbered",
    ) -> PlainTextResponse:
        options = ReportRenderOptions(
            inline_reference_links=inline_reference_links,
            bibliography_source_scope=bibliography,
            source_label_style=source_label_style,
        ).normalized()
        md = await asyncio.to_thread(
            history.render_report_md,
            state.runs_dir,
            run_id,
            render_options=options,
        )
        if md is None:
            raise HTTPException(status_code=404, detail="run not found")
        return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")

    @app.get("/api/history/{run_id}/report/filename")
    async def history_report_filename(
        run_id: str,
        inline_reference_links: bool = True,
        bibliography: str = "inline",
        source_label_style: str = "numbered",
    ) -> dict[str, str]:
        options = ReportRenderOptions(
            inline_reference_links=inline_reference_links,
            bibliography_source_scope=bibliography,
            source_label_style=source_label_style,
        ).normalized()
        md = await asyncio.to_thread(
            history.render_report_md,
            state.runs_dir,
            run_id,
            render_options=options,
        )
        if md is None:
            raise HTTPException(status_code=404, detail="run not found")
        summary = await asyncio.to_thread(history.summarize, state.runs_dir, run_id)
        query = summary.get("query", "") if isinstance(summary, dict) else ""
        filename = await suggest_report_filename(
            local=state.local,
            routing=state.routing,
            query=query,
            report_markdown=md,
            run_id=run_id,
        )
        return {"filename": filename}

    @app.get("/api/history/{run_id}/summary")
    async def history_summary(run_id: str) -> dict:
        summary = await asyncio.to_thread(history.summarize, state.runs_dir, run_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="run not found")
        return summary

    @app.get("/api/note/{run_id}/{note_id}")
    async def get_note(run_id: str, note_id: str) -> dict:
        session = state.registry.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="run not found")
        note = session.notes.get(note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="note not found")
        return note.model_dump(mode="json")

    @app.get("/api/run/{run_id}/summary")
    async def get_run_summary(run_id: str) -> dict:
        """End-of-run debrief: tokens by model, counts, duration.

        Usable mid-run but the Summary tab only flashes after run_done;
        fields like `duration_s` are None until the run finishes.
        """
        session = state.registry.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="run not found")

        # Task count comes from the event history so we don't have to
        # reach into the scheduler state.
        tasks_count = sum(1 for e in session.history if e.kind == "task_started")

        duration_s: float | None = None
        if session.finished_at is not None:
            duration_s = (session.finished_at - session.started_at).total_seconds()

        tokens_payload: dict = {"per_model": {}, "grand_totals": {}}
        if session.tracker is not None:
            tokens_payload = session.tracker.to_dict()

        note_dicts = (n.model_dump(mode="json") for n in session.notes.values())
        return {
            "run_id": session.run_id,
            "query": session.query,
            "finished": session.finished,
            "started_at": session.started_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "duration_s": duration_s,
            "report_note_id": session.report_note_id,
            "tokens": tokens_payload,
            **summarize_notes(note_dicts),
            "tasks": tasks_count,
            "notes_total": len(session.notes),
        }

    # --- Chat endpoints (Phase 1: Ask mode over a finished run) -------------

    @app.post("/api/runs/{run_id}/chat/sessions")
    async def chat_start_session(run_id: str) -> dict:
        """Open a chat session over a finished run's note graph.

        Hydrates a NoteMemory from the run's persisted notes.json and
        returns a session_id the client connects via WS to drive a
        conversation.
        """
        if not history.is_valid_run_id(run_id):
            raise HTTPException(status_code=400, detail="invalid run_id")
        raw_notes = await asyncio.to_thread(history.read_notes, state.runs_dir, run_id)
        if raw_notes is None:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            session = await hydrate_chat_session(
                run_id=run_id,
                raw_notes=raw_notes,
                routing=state.routing,
                local=state.local,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state.chat_registry.add(session)
        logger.info(
            "chat session started session_id=%s run_id=%s notes=%d",
            session.session_id,
            run_id,
            len(list(session.deps.memory.all())),
        )
        return {
            "session_id": session.session_id,
            "run_id": run_id,
            "root_question_id": session.root_question_id,
            "default_model_id": chat_default_model_id(session.deps),
        }

    @app.post("/api/runs/{run_id}/chat/sessions/{session_id}/messages")
    async def chat_send_message(run_id: str, session_id: str, body: ChatMessageRequest) -> dict:
        """Submit a user message; the server runs the turn in the background.

        Returns the turn_id immediately (202-style). Progress + the
        eventual assistant reply land on the WS as
        chat_turn_started / chat_message_assistant / chat_turn_done.
        """
        session = state.chat_registry.get(session_id)
        if session is None or session.run_id != run_id:
            raise HTTPException(status_code=404, detail="chat session not found")
        if not body.content.strip():
            raise HTTPException(status_code=400, detail="content must not be empty")
        if body.mode != "ask":
            # Phase 1: only Ask mode wired through the agent. Phase 2/3
            # add investigate / new_report.
            raise HTTPException(
                status_code=400, detail=f"chat mode {body.mode!r} not supported yet"
            )
        if session.pending_turn is not None and not session.pending_turn.done():
            raise HTTPException(status_code=409, detail="another turn is in progress")

        turn_id = f"turn-{len(session.history):04d}"
        session.pending_turn = asyncio.create_task(
            run_chat_turn(
                session=session,
                mode="ask",
                content=body.content,
                turn_id=turn_id,
                model_id_override=body.model_id,
            )
        )
        return {"turn_id": turn_id, "session_id": session_id}

    @app.get("/api/runs/{run_id}/chat/sessions/{session_id}")
    async def chat_get_session(run_id: str, session_id: str) -> dict:
        session = state.chat_registry.get(session_id)
        if session is None or session.run_id != run_id:
            raise HTTPException(status_code=404, detail="chat session not found")
        return {
            "session_id": session.session_id,
            "run_id": session.run_id,
            "root_question_id": session.root_question_id,
            "created_at": session.created_at.isoformat(),
            "last_activity_at": session.last_activity_at.isoformat(),
            "events": [e.model_dump(mode="json") for e in session.history],
        }

    @app.websocket("/api/ws/chat/{session_id}")
    async def chat_ws(websocket: WebSocket, session_id: str) -> None:
        session = state.chat_registry.get(session_id)
        if session is None:
            await websocket.close(code=4040, reason="chat session not found")
            return
        await websocket.accept()
        queue = session.subscribe()
        n_sent = 0
        try:
            history_snapshot = list(session.history)
            for event in history_snapshot:
                await websocket.send_text(event.model_dump_json())
                n_sent += 1
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json())
                n_sent += 1
        except WebSocketDisconnect:
            logger.info("chat ws disconnect session=%s sent=%d", session_id, n_sent)
        except Exception:
            logger.exception("chat ws error session=%s sent=%d", session_id, n_sent)
        finally:
            session.unsubscribe(queue)

    @app.websocket("/api/ws/{run_id}")
    async def ws(websocket: WebSocket, run_id: str) -> None:
        session = state.registry.get(run_id)
        if session is None:
            logger.warning("ws reject run_id=%s (session not found)", run_id)
            await websocket.close(code=4040, reason="run not found")
            return
        await websocket.accept()
        queue = session.subscribe()
        n_sent = 0
        try:
            history_snapshot = list(session.history)
            logger.info(
                "ws accept run_id=%s replaying %d historical events",
                run_id,
                len(history_snapshot),
            )
            for event in history_snapshot:
                await websocket.send_text(event.model_dump_json())
                n_sent += 1
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json())
                n_sent += 1
                if session.finished and queue.empty():
                    await asyncio.sleep(0.05)
                    if queue.empty():
                        break
        except WebSocketDisconnect:
            logger.info("ws disconnect run_id=%s sent=%d (client closed)", run_id, n_sent)
        except Exception:
            logger.exception("ws error run_id=%s sent=%d", run_id, n_sent)
        else:
            logger.info("ws closed run_id=%s sent=%d (session done)", run_id, n_sent)
        finally:
            session.unsubscribe(queue)

    return app
