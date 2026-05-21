"""Chat-session state + publisher for post-report interactive chat.

A `ChatSession` is to a finished run what `RunSession` is to a live
run: it owns a Deps (with a hydrated NoteMemory loaded from disk),
the running pydantic-ai message history, an event history for WS
replay-on-reconnect, and the in-flight turn task.

Phase 1 ships Ask mode only (read-only over the existing graph).
The session and registry are designed so Phase 2 (investigate, with
graph mutation + per-turn flush) and Phase 3 (new_report) can layer
on without changing the surface.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..agents._run import drive_agent_with_history
from ..agents.chat import ChatMode, build_chat_agent
from ..agents.deps import Deps, build_deps, close_deps
from ..agents.events import EventPublisher
from ..agents.memory import NoteMemory
from ..config import LocalConfig, RoutingConfig
from ..schemas.enums import (
    AgentRunStatus,
    AgentType,
    NoteType,
    RoleClass,
    TaskTier,
)
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata
from .events import (
    Event,
    event_agent_done,
    event_agent_started,
    event_chat_message_assistant,
    event_chat_message_user,
    event_chat_turn_done,
    event_chat_turn_started,
    event_note_created,
    event_note_replaced,
    event_token_usage,
    event_tool_call_end,
    event_tool_call_start,
)

logger = logging.getLogger(__name__)


HISTORY_CAP = 5_000


def _hydrate_notes(raw_notes: Iterable[dict[str, Any]]) -> list[Note]:
    """Parse a list of note-dicts (from notes.json) into Note objects.

    Hydration drift on legacy / partially-migrated runs is silent —
    individual notes that fail validation are skipped with a logged
    warning so a single broken record doesn't kill a chat session.
    """
    out: list[Note] = []
    n_skipped = 0
    for raw in raw_notes:
        try:
            out.append(Note.model_validate(raw))
        except ValidationError as exc:
            n_skipped += 1
            logger.warning(
                "chat hydration skipped note id=%s: %s",
                (raw or {}).get("id"),
                str(exc)[:160],
            )
    if n_skipped:
        logger.warning("chat hydration: %d note(s) skipped due to validation errors", n_skipped)
    return out


def _find_root_question_id(memory: NoteMemory) -> NoteID | None:
    """Root question = the QUESTION note with no parent."""
    for n in memory.list_by_type(NoteType.QUESTION):
        meta = n.metadata
        if isinstance(meta, QuestionMetadata) and meta.parent_question_id is None:
            return n.id
    return None


@dataclass
class ChatSession:
    """One open chat session over a finished run's note graph.

    Owns the hydrated Deps, message history, and event stream. The
    registry holds at most one active in-flight turn per session so
    concurrent submits return 409 (handled in the endpoint layer).
    """

    session_id: str
    run_id: str
    deps: Deps
    root_question_id: NoteID
    budget_box: list[int] = field(default_factory=lambda: [0])
    message_history: list[Any] = field(default_factory=list)
    history: deque[Event] = field(default_factory=lambda: deque(maxlen=HISTORY_CAP))
    subscribers: set[asyncio.Queue[Event]] = field(default_factory=set)
    pending_turn: asyncio.Task[None] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def publish(self, event: Event) -> None:
        self.history.append(event)
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # unbounded queue; defensive only
                logger.warning("chat subscriber queue full session=%s", self.session_id)

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self.subscribers.discard(q)

    def touch(self) -> None:
        self.last_activity_at = datetime.now(UTC)


class ChatPublisher(EventPublisher):
    """EventPublisher that fans agent + note events into a ChatSession.

    Mirrors `SessionPublisher` (server/runner.py) shape so the live UI
    can reuse the existing tool-ticker / agent-card listeners over the
    chat WebSocket without the frontend caring whether events came
    from a live run or a chat turn.

    Two-step construction: instantiate first (deps need an
    `EventPublisher` before the session can be built), then call
    `bind(session)` once the ChatSession exists. Until bound, events
    are dropped — only callers that know the wire-up order should be
    constructing instances.
    """

    def __init__(self) -> None:
        self._session: ChatSession | None = None

    def bind(self, session: ChatSession) -> None:
        self._session = session

    def _publish(self, event: Event) -> None:
        if self._session is not None:
            self._session.publish(event)

    def on_agent_start(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        goal: str,
        tier: TaskTier,
        role: RoleClass,
        model_id: str | None,
        mode: str | None = None,
    ) -> None:
        self._publish(
            event_agent_started(
                agent_id=agent_id,
                agent_type=agent_type.value,
                goal=goal,
                tier=tier.value,
                role=role.value,
                model_id=model_id,
                mode=mode,
            )
        )

    def on_agent_done(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        status: AgentRunStatus,
        verdict: str,
    ) -> None:
        self._publish(
            event_agent_done(
                agent_id=agent_id,
                agent_type=agent_type.value,
                status=status.value,
                verdict=verdict,
            )
        )

    def on_note_created(self, note: Note) -> None:
        self._publish(event_note_created(note))

    def on_note_replaced(self, note: Note) -> None:
        self._publish(event_note_replaced(note))

    def on_tool_start(self, *, agent_id: str, tool_call_id: str, tool: str, summary: str) -> None:
        self._publish(
            event_tool_call_start(
                agent_id=agent_id, tool_call_id=tool_call_id, tool=tool, summary=summary
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
        self._publish(
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
        agent_type: AgentType,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None:
        self._publish(
            event_token_usage(
                agent_id=agent_id,
                agent_type=agent_type.value,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
        )


async def hydrate_chat_session(
    *,
    run_id: str,
    raw_notes: Iterable[dict[str, Any]],
    routing: RoutingConfig,
    local: LocalConfig,
) -> ChatSession:
    """Build a ChatSession from a run's persisted notes.

    Wires a fresh Deps (so retrieval clients are available for
    Phase 2's investigate mode), then replaces its memory with a
    NoteMemory hydrated from the notes list. The publisher is bound
    to the new ChatSession so events flow into the session's history
    and to live WS subscribers.
    """
    notes = _hydrate_notes(raw_notes)
    if not notes:
        raise ValueError(f"no valid notes hydrated for run_id={run_id}")

    session_id = f"chat-{uuid.uuid4().hex[:12]}"
    # Publisher is constructed unbound; the session binds it once it
    # exists. Until bound, .publish drops events on the floor —
    # acceptable because no agent runs before bind() is called.
    publisher = ChatPublisher()
    deps = build_deps(local, routing, events=publisher)
    memory = await NoteMemory.from_notes(notes, publisher=publisher)
    deps.memory = memory

    root_id = _find_root_question_id(memory)
    if root_id is None:
        await close_deps(deps)
        raise ValueError(f"no root question note found in run_id={run_id}")

    session = ChatSession(
        session_id=session_id,
        run_id=run_id,
        deps=deps,
        root_question_id=root_id,
    )
    publisher.bind(session)
    return session


async def run_chat_turn(
    *,
    session: ChatSession,
    mode: ChatMode,
    content: str,
    turn_id: str,
    model_id_override: str | None = None,
) -> None:
    """Execute one chat turn end-to-end. Publishes events as it runs.

    Captures any exception, surfaces it as a `chat_turn_done` with
    status=error so the UI can display the failure. Never propagates
    out — the caller schedules this as a background task and the WS
    is the only feedback channel.

    `model_id_override` lets the UI pin a specific model per message
    (the chat panel's model dropdown). When None, falls back to the
    routing config default.
    """
    session.touch()
    session.publish(
        event_chat_message_user(
            session_id=session.session_id, mode=mode, content=content, turn_id=turn_id
        )
    )
    session.publish(
        event_chat_turn_started(session_id=session.session_id, turn_id=turn_id, mode=mode)
    )
    try:
        agent, model_id = build_chat_agent(
            session.deps,
            mode=mode,
            root_question_id=session.root_question_id,
            budget_box=session.budget_box,
            model_id_override=model_id_override,
        )
        agent_id = f"chat-{uuid.uuid4().hex[:8]}"
        output, new_history = await drive_agent_with_history(
            deps=session.deps,
            agent=agent,
            agent_id=agent_id,
            agent_type=AgentType.CHAT,
            goal=content[:200],
            tier=TaskTier.MID,
            role=RoleClass.GENERATIVE,
            model_id=model_id,
            prompt=content,
            message_history=session.message_history or None,
            mode=mode,
        )
        session.message_history = new_history
        assistant_text = output if isinstance(output, str) else (str(output) if output else "")
        session.deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type=AgentType.CHAT,
            status=AgentRunStatus.DONE,
            verdict=f"chat reply ({len(assistant_text)} chars)",
        )
        session.publish(
            event_chat_message_assistant(
                session_id=session.session_id, content=assistant_text, turn_id=turn_id
            )
        )
        session.publish(
            event_chat_turn_done(session_id=session.session_id, turn_id=turn_id, status="ok")
        )
    except Exception as exc:
        logger.exception("chat turn failed session=%s turn=%s", session.session_id, turn_id)
        session.publish(
            event_chat_turn_done(
                session_id=session.session_id,
                turn_id=turn_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
        )
    finally:
        session.touch()


class ChatRegistry:
    """Process-wide registry of open chat sessions.

    Caps retained sessions at `max_sessions`; evicts oldest by
    creation order when full and closes their Deps. Future phases add
    a per-run lock here so concurrent investigate-mode turns on the
    same run serialize their notes.json rewrites.
    """

    def __init__(self, max_sessions: int = 100) -> None:
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()
        self._max_sessions = max_sessions
        # Hold strong refs to in-flight close tasks so they aren't GC'd
        # before they finish releasing the http_client pool.
        self._close_tasks: set[asyncio.Task[None]] = set()

    def add(self, session: ChatSession) -> None:
        self._sessions[session.session_id] = session
        while len(self._sessions) > self._max_sessions:
            evicted_id, evicted = self._sessions.popitem(last=False)
            logger.info("chat session evicted session_id=%s", evicted_id)
            task = asyncio.create_task(self._close(evicted))
            self._close_tasks.add(task)
            task.add_done_callback(self._close_tasks.discard)

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def all(self) -> list[ChatSession]:
        return list(self._sessions.values())

    async def _close(self, session: ChatSession) -> None:
        try:
            await close_deps(session.deps)
        except Exception:
            logger.exception("close_deps failed for chat session=%s", session.session_id)
