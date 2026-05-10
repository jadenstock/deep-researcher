"""Event types + per-run event bus.

Events are the UI's view of what an agent run is doing. The wire
protocol (kinds + payload shapes) matches what the live UI
(`server/static/index.html`) expects:

    run_started   -> { run_id, query }
    task_started  -> AgentSummary (id, type, goal, status, tier, role,
                                    model_id, started_at, parent_id?,
                                    reads_notes=[], writes_notes=[])
    task_done     -> { id, type, status, verdict }
    note_created  -> NoteSummary
    note_replaced -> NoteSummary
    run_done      -> { report_note_id }
    run_failed    -> { error }

Keeping the "task_*" kind names means the existing UI (which
originally tracked scheduler tasks) renders our agent invocations
without frontend changes - each agent is a "task" in UI terms.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas.note import Note

logger = logging.getLogger(__name__)


# --- Wire payloads ----------------------------------------------------------


class NoteSummary(BaseModel):
    """Lightweight note projection - full content fetched via /api/note/..."""

    id: str
    type: str
    subtype: str | None = None
    title: str
    description: str
    by_task_id: str | None = None
    links: list[dict[str, str]] = Field(default_factory=list)
    version: int = 1

    @classmethod
    def from_note(cls, note: Note) -> NoteSummary:
        subtype = getattr(note.metadata, "category", None)
        return cls(
            id=note.id,
            type=note.type.value,
            subtype=subtype,
            title=note.title,
            description=note.description,
            by_task_id=note.last_modified_by or note.created_by,
            links=[
                {"target_id": link.target_id, "edge_type": link.edge_type} for link in note.links
            ],
            version=note.version,
        )


class AgentSummary(BaseModel):
    """Projection of an agent invocation onto the wire.

    Shape matches the UI's `addAgentCard` expectations. `reads_notes`
    and `writes_notes` stay empty for agents (we don't pre-declare
    them) - the UI falls back to `[]`.
    """

    id: str
    type: str
    goal: str
    status: str
    parent_id: str | None = None
    reads_notes: list[str] = Field(default_factory=list)
    writes_notes: list[str] = Field(default_factory=list)
    pattern: str | None = None
    tier: str | None = None
    role: str | None = None
    model_id: str | None = None
    started_at: datetime | None = None


# --- Event envelope ---------------------------------------------------------


class Event(BaseModel):
    kind: Literal[
        "run_started",
        "task_started",
        "task_done",
        "note_created",
        "note_replaced",
        "tool_call_start",
        "tool_call_end",
        "run_done",
        "run_failed",
    ]
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]


def event_run_started(run_id: str, query: str) -> Event:
    return Event(kind="run_started", data={"run_id": run_id, "query": query})


def event_agent_started(
    *,
    agent_id: str,
    agent_type: str,
    goal: str,
    tier: str | None,
    role: str | None,
    model_id: str | None,
    parent_id: str | None = None,
) -> Event:
    summary = AgentSummary(
        id=agent_id,
        type=agent_type,
        goal=goal,
        status="RUNNING",
        parent_id=parent_id,
        tier=tier,
        role=role,
        model_id=model_id,
        started_at=datetime.now(UTC),
    )
    return Event(kind="task_started", data=summary.model_dump(mode="json"))


def event_agent_done(
    *,
    agent_id: str,
    agent_type: str,
    status: str,
    verdict: str,
) -> Event:
    return Event(
        kind="task_done",
        data={
            "id": agent_id,
            "type": agent_type,
            "status": status,
            "verdict": verdict,
        },
    )


def event_note_created(note: Note) -> Event:
    return Event(
        kind="note_created",
        data=NoteSummary.from_note(note).model_dump(),
    )


def event_note_replaced(note: Note) -> Event:
    return Event(
        kind="note_replaced",
        data=NoteSummary.from_note(note).model_dump(),
    )


def event_tool_call_start(
    *,
    agent_id: str,
    tool_call_id: str,
    tool: str,
    summary: str,
) -> Event:
    return Event(
        kind="tool_call_start",
        data={
            "agent_id": agent_id,
            "tool_call_id": tool_call_id,
            "tool": tool,
            "summary": summary,
        },
    )


def event_tool_call_end(
    *,
    agent_id: str,
    tool_call_id: str,
    tool: str,
    status: str,
    summary: str,
    duration_ms: int,
) -> Event:
    return Event(
        kind="tool_call_end",
        data={
            "agent_id": agent_id,
            "tool_call_id": tool_call_id,
            "tool": tool,
            "status": status,
            "summary": summary,
            "duration_ms": duration_ms,
        },
    )


def event_run_done(report_note_id: str | None) -> Event:
    return Event(kind="run_done", data={"report_note_id": report_note_id})


def event_run_failed(error: str) -> Event:
    return Event(kind="run_failed", data={"error": error})


# --- Per-run session --------------------------------------------------------


class RunSession:
    """Owns the event history + subscribers for one run.

    History is bounded so long sessions don't leak memory; late
    WebSocket connectors replay from the tail. Pub/sub uses unbounded
    queues on the assumption subscribers drain promptly - they're
    WebSocket handlers.
    """

    HISTORY_CAP = 5_000

    def __init__(self, run_id: str, query: str) -> None:
        self.run_id = run_id
        self.query = query
        self.started_at = datetime.now(UTC)
        self.finished = False
        self.history: list[Event] = []
        self.subscribers: set[asyncio.Queue[Event]] = set()
        # Captured as notes flow by so /api/note can answer without
        # reaching into agent memory from another coroutine.
        self.notes: dict[str, Note] = {}
        # Holds the asyncio.Task running the session so it isn't GC'd.
        self.task: asyncio.Task[None] | None = None

    def publish(self, event: Event) -> None:
        self.history.append(event)
        if len(self.history) > self.HISTORY_CAP:
            self.history = self.history[-self.HISTORY_CAP :]
        n_subs = len(self.subscribers)
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # unbounded queue; defensive only
                logger.warning("subscriber queue full run_id=%s", self.run_id)
        # Visible at INFO so the user can diagnose a silent UI: if the
        # server log shows kind=task_started subs=0, the WS isn't
        # connected yet; kind=... subs>0 means events are being pushed.
        logger.info(
            "publish run_id=%s kind=%s subs=%d hist=%d",
            self.run_id,
            event.kind,
            n_subs,
            len(self.history),
        )

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
