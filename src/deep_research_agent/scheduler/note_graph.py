"""Note graph — owns note state and write semantics.

Writes are serialized by the Scheduler's write lock. This class does not
do its own locking; it assumes callers hold the scheduler lock when
invoking mutating methods. Read methods are safe to call concurrently.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from ..schemas import Note, NoteID, NoteType, TaskID


class NoteVersionConflict(RuntimeError):
    """Raised when a conditional write targets a stale version."""


class NoteGraph:
    def __init__(self) -> None:
        self._notes: dict[NoteID, Note] = {}

    # --- read methods ------------------------------------------------------

    def get(self, note_id: NoteID) -> Note:
        return self._notes[note_id]

    def by_type(self, note_type: NoteType) -> list[Note]:
        return [n for n in self._notes.values() if n.type == note_type]

    def all(self) -> Iterable[Note]:
        return self._notes.values()

    def __len__(self) -> int:
        return len(self._notes)

    def __contains__(self, note_id: object) -> bool:
        return note_id in self._notes

    # --- write methods (called under scheduler lock) -----------------------

    def add(self, note: Note) -> NoteID:
        if note.id in self._notes:
            raise ValueError(f"Note {note.id} already in graph")
        self._notes[note.id] = note
        return note.id

    def replace(
        self,
        note: Note,
        by: TaskID,
        expected_version: int | None = None,
    ) -> None:
        """Replace a note in place, bumping version and modification stamps.

        If expected_version is provided, raise NoteVersionConflict when the
        current version doesn't match. v0 does not use optimistic
        concurrency — callers pass None — but the hook is here for when
        parallel synthesis tasks need to coordinate.
        """
        if note.id not in self._notes:
            raise KeyError(f"Note {note.id} not in graph; use add() for new notes")
        existing = self._notes[note.id]
        if expected_version is not None and existing.version != expected_version:
            raise NoteVersionConflict(
                f"Note {note.id} is at version {existing.version}, "
                f"write expected version {expected_version}"
            )
        self._notes[note.id] = note.model_copy(
            update={
                "version": existing.version + 1,
                "last_modified_by": by,
                "last_modified_at": datetime.now(UTC),
            }
        )
