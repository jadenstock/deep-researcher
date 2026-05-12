"""Shared note graph - the agents' persistent memory across a run.

All agents (top-level researcher + every sub-agent) share one
`NoteMemory` via `Deps`. Concurrent tool calls read/write it through
an asyncio lock so a parallel fan-out doesn't race on the dict.

Only the tool layer (agents/tools/notes.py) should touch memory
directly; agent bodies go through their tools.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from ..schemas.enums import NoteType
from ..schemas.ids import NoteID
from ..schemas.note import Note, SourceNoteMetadata
from .events import EventPublisher, NoOpPublisher


def new_note_id(prefix: str) -> NoteID:
    return NoteID(f"{prefix}-{uuid.uuid4().hex[:12]}")


def _normalize_url(url: str) -> str:
    u = url.strip().rstrip("/")
    # Lowercase scheme + host only - keep path case-sensitive.
    if "://" in u:
        scheme, rest = u.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
            u = f"{scheme.lower()}://{host.lower()}/{path}"
        else:
            u = f"{scheme.lower()}://{rest.lower()}"
    return u


class NoteMemory:
    """Async-safe note graph keyed by NoteID.

    The underlying store is a plain dict; the lock serializes
    create/update/list operations across concurrent tool calls. Reads
    (`get`) don't lock - Python dict reads are atomic at the GIL
    level, and a stale read here just means the agent sees a slightly
    older snapshot of its corpus, which is acceptable.

    An optional `publisher` is notified on every successful
    create/update so a UI layer (or any observer) can react. The
    publisher call is synchronous and happens *after* the lock is
    released so observer work never stalls other mutations.

    Secondary indexes:
      _by_type: NoteType -> insertion-ordered NoteIDs. Materializes
        list_by_type in O(matched) instead of O(all notes).
      _by_source_url: normalized source URL -> NoteID. Makes
        find_source_by_url O(1).
    """

    def __init__(self, publisher: EventPublisher | None = None) -> None:
        self._notes: dict[NoteID, Note] = {}
        self._by_type: dict[NoteType, list[NoteID]] = {}
        self._by_source_url: dict[str, NoteID] = {}
        self._lock = asyncio.Lock()
        self._publisher: EventPublisher = publisher or NoOpPublisher()

    def __len__(self) -> int:
        return len(self._notes)

    async def create(self, note: Note) -> Note:
        async with self._lock:
            if note.id in self._notes:
                raise ValueError(f"note {note.id} already exists")
            self._notes[note.id] = note
            self._by_type.setdefault(note.type, []).append(note.id)
            if isinstance(note.metadata, SourceNoteMetadata):
                self._by_source_url[_normalize_url(note.metadata.url)] = note.id
        self._publisher.on_note_created(note)
        return note

    async def update(self, note_id: NoteID, **fields: object) -> Note:
        """Replace the named fields on an existing note.

        Pydantic's `model_copy(update=...)` validates the replacement.
        Version bumps on every update so a dashboard could detect churn.
        """
        async with self._lock:
            existing = self._notes.get(note_id)
            if existing is None:
                raise KeyError(f"note {note_id} does not exist")
            merged_fields = {
                **fields,
                "version": existing.version + 1,
                "last_modified_at": datetime.now(UTC),
            }
            updated = existing.model_copy(update=merged_fields)
            self._notes[note_id] = updated
            if isinstance(existing.metadata, SourceNoteMetadata) and isinstance(
                updated.metadata, SourceNoteMetadata
            ):
                old_key = _normalize_url(existing.metadata.url)
                new_key = _normalize_url(updated.metadata.url)
                if old_key != new_key:
                    self._by_source_url.pop(old_key, None)
                    self._by_source_url[new_key] = note_id
        self._publisher.on_note_replaced(updated)
        return updated

    def get(self, note_id: NoteID) -> Note | None:
        return self._notes.get(note_id)

    def list_by_type(self, note_type: NoteType) -> list[Note]:
        ids = self._by_type.get(note_type, ())
        return [self._notes[nid] for nid in ids]

    def count_by_type(self, note_type: NoteType) -> int:
        return len(self._by_type.get(note_type, ()))

    def find_source_by_url(self, url: str) -> Note | None:
        """Return the existing source note for this URL, or None.

        URLs are compared with trivial normalization - strip trailing
        slash and case-fold the scheme/host. Good enough to dedup
        identical links from different search providers; not a full
        canonicalizer.
        """
        note_id = self._by_source_url.get(_normalize_url(url))
        if note_id is None:
            return None
        return self._notes.get(note_id)

    def all(self) -> Iterable[Note]:
        return list(self._notes.values())
