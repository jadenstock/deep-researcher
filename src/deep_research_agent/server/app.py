"""FastAPI app — starts runs, streams events over WebSocket.

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
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import (
    LocalConfig,
    PipelineConfig,
    RoutingConfig,
    load_local_config,
    load_pipeline_config,
    load_routing_config,
)
from ..observability import setup_logfire
from ..retrieval.brave import set_brave_min_interval
from ..scheduler import new_run_id
from .events import SessionRegistry
from .runner import run_session

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_logging() -> None:
    """Set up split-level logging: clean console, verbose per-run files.

    The root logger runs at DEBUG so DEBUG records can flow through to
    handlers. Each handler then caps its own level:
      - Console (stderr): DRA_LOG_LEVEL (default INFO) so your terminal
        stays readable.
      - Per-run FileHandler (attached by runner.py at run start): DEBUG
        unconditionally so the on-disk run.log is a complete diagnostic
        artifact every time. You never have to remember an env var to
        capture debug detail when something goes wrong.
      - Optional DRA_LOG_FILE FileHandler: DRA_LOG_LEVEL. Useful for
        long-lived process-wide logs where you want the same verbosity
        as the console.

    DRA_LOG_LEVEL controls the *console* level only. Set it to DEBUG if
    you want debug lines on stderr too.
    """
    console_level_name = os.environ.get("DRA_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_name, logging.INFO)
    root = logging.getLogger()
    # Root must be DEBUG (most permissive) so handlers can decide their
    # own cap. If root is INFO, DEBUG records never reach any handler
    # regardless of the handler's level — the root acts as a pre-gate.
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        # basicConfig would set root to a fixed level; build the console
        # handler ourselves so we can level it independently.
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_LOG_FORMAT))
        console.setLevel(console_level)
        root.addHandler(console)
    else:
        # Handlers already attached (uvicorn). Adjust any StreamHandlers
        # to the configured console level but leave FileHandlers alone
        # since they have their own policy.
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(console_level)

    log_file = os.environ.get("DRA_LOG_FILE")
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Guard against a re-configure adding a second FileHandler for
        # the same path (process-local but still easy to hit on reload).
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

    # The dra package's own loggers must also be DEBUG so their records
    # reach the root (package-level loggers otherwise cap below DEBUG
    # by default). Noisy third-party loggers (httpx, uvicorn.access)
    # keep their defaults — their verbosity policy is their own.
    logging.getLogger("deep_research_agent").setLevel(logging.DEBUG)


_configure_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class RunRequest(BaseModel):
    query: str


class ServerState:
    """Holds the configs + registry for the lifetime of the server."""

    def __init__(
        self,
        routing: RoutingConfig,
        local: LocalConfig,
        pipeline: PipelineConfig,
        runs_dir: Path,
    ) -> None:
        self.routing = routing
        self.local = local
        self.pipeline = pipeline
        self.runs_dir = runs_dir
        self.registry = SessionRegistry()


def create_app(
    routing_path: Path | str = "config/routing_diverse.yaml",
    local_path: Path | str = "config/local.toml",
    pipeline_path: Path | str = "config/pipeline.yaml",
    runs_dir: Path | str = "runs",
) -> FastAPI:
    """Build and return a configured FastAPI app."""
    local = load_local_config(local_path)
    routing = load_routing_config(routing_path)
    pipeline = load_pipeline_config(pipeline_path)
    setup_logfire(local)
    set_brave_min_interval(local.retrieval.brave_min_interval_s)

    state = ServerState(
        routing=routing,
        local=local,
        pipeline=pipeline,
        runs_dir=Path(runs_dir),
    )

    app = FastAPI(title="deep-research-agent live UI")

    @app.get("/")
    async def index() -> FileResponse:
        if not INDEX_HTML.exists():
            raise HTTPException(status_code=500, detail="index.html missing")
        # Force the browser to fetch fresh HTML on every page load. The
        # UI is iterated on frequently and stale JS gets blamed on the
        # backend more than once — easier to pay the reload cost.
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
        # Task is stored on the session so it isn't GC'd mid-run and so a
        # future cancel endpoint can reach it.
        session.task = asyncio.create_task(
            run_session(
                session,
                state.routing,
                state.local,
                state.pipeline,
                state.runs_dir,
            )
        )
        logger.info("run queued run_id=%s query=%r", run_id, body.query[:80])
        return {"run_id": run_id}

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

    @app.get("/api/note/{run_id}/{note_id}")
    async def get_note(run_id: str, note_id: str) -> dict:
        session = state.registry.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="run not found")
        note = session.notes.get(note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="note not found")
        return note.model_dump(mode="json")

    @app.websocket("/api/ws/{run_id}")
    async def ws(websocket: WebSocket, run_id: str) -> None:
        session = state.registry.get(run_id)
        if session is None:
            await websocket.close(code=4040, reason="run not found")
            return
        await websocket.accept()
        queue = session.subscribe()
        try:
            # Replay history for late connectors so the UI catches up.
            for event in list(session.history):
                await websocket.send_text(event.model_dump_json())
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json())
                if session.finished and queue.empty():
                    # Give a moment for any trailing events, then close cleanly.
                    await asyncio.sleep(0.05)
                    if queue.empty():
                        break
        except WebSocketDisconnect:
            logger.info("ws disconnect run_id=%s", run_id)
        finally:
            session.unsubscribe(queue)

    return app
