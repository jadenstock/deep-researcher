"""ID generation for tasks, notes, and runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..schemas.ids import NoteID, RunID, TaskID


def new_task_id() -> TaskID:
    return TaskID(f"task_{uuid.uuid4().hex[:10]}")


def new_note_id(prefix: str = "note") -> NoteID:
    return NoteID(f"{prefix}_{uuid.uuid4().hex[:10]}")


def new_run_id() -> RunID:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return RunID(f"run_{ts}_{uuid.uuid4().hex[:4]}")
