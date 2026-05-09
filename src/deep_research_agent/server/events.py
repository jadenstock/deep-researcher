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

from ..config import RoutingConfig
from ..schemas import Note, Task

logger = logging.getLogger(__name__)


# --- Event models -----------------------------------------------------------


class NoteSummary(BaseModel):
    """Lightweight note projection — full content fetched via /api/note/..."""

    id: str
    type: str
    # Sub-type indicator for the UI. Currently populated from
    # DecisionMetadata.category (e.g. "aims_scoping", "verification",
    # "final_report") so the frontend can distinguish decision flavors
    # without a full schema walk.
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


class TaskSummary(BaseModel):
    """Projection of a Task onto the wire for the running-agents UI.

    Fields beyond the basic identity are what lets the UI render a card
    with enough context to answer "what is this agent doing?" without
    a secondary fetch: the notes it reads + writes, the pattern, tier,
    role, and which model it's routed to.
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
    # Resolved at event-emit time via routing.model_id_for(role, tier).
    # For VERIFY_CLAIM the executor may additionally apply the ADR 0008
    # cross-family invariant and select a different model; this field
    # reflects the default-family resolution, close enough for the UI
    # indicator. The run.log captures the actual model used.
    model_id: str | None = None
    started_at: datetime | None = None

    @classmethod
    def from_task(cls, task: Task, routing: RoutingConfig | None = None) -> TaskSummary:
        model_id: str | None = None
        if routing is not None:
            try:
                model_id = routing.model_id_for(task.role, task.tier)
            except Exception:
                # Routing miss (e.g. role/tier combo not in config) is
                # not fatal — the UI just doesn't get a model label.
                model_id = None
        return cls(
            id=task.id,
            type=task.type.value,
            goal=task.goal,
            status=task.status.value,
            parent_id=task.parent_id,
            reads_notes=list(task.reads_notes),
            writes_notes=list(task.writes_notes),
            pattern=task.pattern.value if task.pattern is not None else None,
            tier=task.tier.value,
            role=task.role.value,
            model_id=model_id,
            started_at=datetime.now(UTC),
        )


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


def event_task_started(task: Task, routing: RoutingConfig | None = None) -> Event:
    return Event(
        kind="task_started",
        data=TaskSummary.from_task(task, routing).model_dump(mode="json"),
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


def event_replan_started(
    cycle_num: int, routing: RoutingConfig | None = None
) -> tuple[Event, str]:
    """Synthetic task_started event for a replanner cycle.

    The replanner runs between scheduler ticks and doesn't go through
    the normal task dispatch path, so `on_task_start` never fires for
    it. But it's a live agent spinning on a judgment model for seconds
    at a time — the user wants to see it in the Running Agents panel.
    We emit a task_started event with a synthetic id; the caller pairs
    it with event_replan_done via the returned id string.

    Returns (Event, synthetic_task_id) so the caller can hand the id
    back to event_replan_done later.
    """
    from ..schemas.enums import RoleClass, TaskTier

    synth_id = f"replan_cycle_{cycle_num:02d}"
    model_id: str | None = None
    if routing is not None:
        try:
            model_id = routing.model_id_for(RoleClass.JUDGMENT, TaskTier.MID)
        except Exception:
            model_id = None
    summary = TaskSummary(
        id=synth_id,
        type="REPLAN",
        goal=(
            "Re-assess graph state; spawn/abandon/escalate sub-questions "
            "as evidence warrants."
        ),
        status="RUNNING",
        tier="MID",
        role="judgment",
        model_id=model_id,
        started_at=datetime.now(UTC),
    )
    return Event(kind="task_started", data=summary.model_dump(mode="json")), synth_id


def event_replan_done(synth_id: str, verdict: str, failed: bool = False) -> Event:
    """Companion to event_replan_started — closes the synthetic card.

    status is DONE on success, ABANDONED on replanner failure so the UI
    flashes red rather than green before fading.
    """
    return Event(
        kind="task_done",
        data={
            "id": synth_id,
            "type": "REPLAN",
            "status": "ABANDONED" if failed else "DONE",
            "verdict": verdict,
        },
    )


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
