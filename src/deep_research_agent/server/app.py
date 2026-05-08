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
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import LocalConfig, RoutingConfig, load_local_config, load_routing_config
from ..observability import setup_logfire
from ..retrieval.brave import set_brave_min_interval
from ..scheduler import new_run_id
from .events import SessionRegistry
from .runner import run_session

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class RunRequest(BaseModel):
    query: str


class ServerState:
    """Holds the configs + registry for the lifetime of the server."""

    def __init__(self, routing: RoutingConfig, local: LocalConfig, runs_dir: Path) -> None:
        self.routing = routing
        self.local = local
        self.runs_dir = runs_dir
        self.registry = SessionRegistry()


def create_app(
    routing_path: Path | str = "config/routing_diverse.yaml",
    local_path: Path | str = "config/local.toml",
    runs_dir: Path | str = "runs",
) -> FastAPI:
    """Build and return a configured FastAPI app."""
    local = load_local_config(local_path)
    routing = load_routing_config(routing_path)
    setup_logfire(local)
    set_brave_min_interval(local.retrieval.brave_min_interval_s)

    state = ServerState(routing=routing, local=local, runs_dir=Path(runs_dir))

    app = FastAPI(title="deep-research-agent live UI")

    @app.get("/")
    async def index() -> FileResponse:
        if not INDEX_HTML.exists():
            raise HTTPException(status_code=500, detail="index.html missing")
        return FileResponse(INDEX_HTML)

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
            run_session(session, state.routing, state.local, state.runs_dir)
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
