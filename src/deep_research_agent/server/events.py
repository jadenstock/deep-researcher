"""Event types + per-run event bus.

Events are the UI's view of scheduler state. Each run owns a RunSession
with a bounded history (for late WebSocket connectors) and a set of
subscriber queues. The scheduler's callbacks push events onto the
session; the WebSocket handler pulls them off per-subscriber queue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas import Note, Task

logger = logging.getLogger(__name__)


# --- Event models -----------------------------------------------------------


class NoteSummary(BaseModel):
    """Lightweight note projection — full content fetched via /api/note/..."""

    id: str
    type: str
    title: str
    description: str
    by_task_id: str | None = None
    links: list[dict[str, str]] = Field(default_factory=list)
    version: int = 1

    @classmethod
    def from_note(cls, note: Note) -> NoteSummary:
        return cls(
            id=note.id,
            type=note.type.value,
            title=note.title,
            description=note.description,
            by_task_id=note.last_modified_by or note.created_by,
            links=[
                {"target_id": link.target_id, "edge_type": link.edge_type} for link in note.links
            ],
            version=note.version,
        )


class TaskSummary(BaseModel):
    id: str
    type: str
    goal: str
    status: str
    parent_id: str | None = None


class Event(BaseModel):
    kind: Literal[
        "run_started",
        "task_started",
        "task_done",
        "note_created",
        "note_replaced",
        "run_done",
        "run_failed",
    ]
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]


def event_run_started(run_id: str, query: str) -> Event:
    return Event(kind="run_started", data={"run_id": run_id, "query": query})


def event_task_started(task: Task) -> Event:
    return Event(
        kind="task_started",
        data=TaskSummary(
            id=task.id,
            type=task.type.value,
            goal=task.goal,
            status=task.status.value,
            parent_id=task.parent_id,
        ).model_dump(),
    )


def event_task_done(task: Task, verdict: str) -> Event:
    return Event(
        kind="task_done",
        data={
            "id": task.id,
            "type": task.type.value,
            "status": task.status.value,
            "verdict": verdict,
        },
    )


def event_note_created(note: Note) -> Event:
    return Event(kind="note_created", data=NoteSummary.from_note(note).model_dump())


def event_note_replaced(note: Note) -> Event:
    return Event(kind="note_replaced", data=NoteSummary.from_note(note).model_dump())


def event_run_done(report_note_id: str | None) -> Event:
    return Event(kind="run_done", data={"report_note_id": report_note_id})


def event_run_failed(error: str) -> Event:
    return Event(kind="run_failed", data={"error": error})


# --- Per-run session --------------------------------------------------------


class RunSession:
    """Owns the event history + subscribers for one run.

    History is bounded to avoid memory creep on long sessions; late
    WebSocket connectors get a replay from the tail. Pub/sub uses
    unbounded queues on the assumption subscribers drain promptly —
    they're WebSocket handlers.
    """

    HISTORY_CAP = 5_000

    def __init__(self, run_id: str, query: str) -> None:
        self.run_id = run_id
        self.query = query
        self.started_at = datetime.now(UTC)
        self.finished = False
        self.history: list[Event] = []
        self.subscribers: set[asyncio.Queue[Event]] = set()
        # Notes captured as they're created/replaced so /api/note can return
        # the full object without reaching into scheduler internals.
        self.notes: dict[str, Note] = {}
        # Holds the asyncio.Task running the session so it isn't GC'd mid-run.
        self.task: asyncio.Task[None] | None = None

    def publish(self, event: Event) -> None:
        self.history.append(event)
        if len(self.history) > self.HISTORY_CAP:
            self.history = self.history[-self.HISTORY_CAP :]
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # unbounded queue; defensive only
                logger.warning("subscriber queue full run_id=%s", self.run_id)

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self.subscribers.discard(q)


class SessionRegistry:
    """Process-wide registry of active RunSessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, RunSession] = {}

    def create(self, run_id: str, query: str) -> RunSession:
        session = RunSession(run_id, query)
        self._sessions[run_id] = session
        return session

    def get(self, run_id: str) -> RunSession | None:
        return self._sessions.get(run_id)

    def all(self) -> list[RunSession]:
        return list(self._sessions.values())
