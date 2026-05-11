"""Read past runs from the `runs/` directory on disk.

The live UI's SessionRegistry only remembers runs from the current server
process. This module serves the complementary view: completed runs whose
artifacts are still on disk, regardless of server uptime.

Only the new-format run-id (`YYYYMMDDTHHMMSS-xxxxxxxx`, see run_id.py) is
recognized. Legacy `run_*_xxxx` directories are ignored.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{8}$")


def is_valid_run_id(run_id: str) -> bool:
    """Guard against path traversal and legacy ids in one shot."""
    return bool(RUN_ID_RE.match(run_id))


def _started_at(run_id: str) -> datetime:
    stamp = run_id.split("-", 1)[0]
    return datetime.strptime(stamp, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)


def _root_question(notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for n in notes:
        if n.get("type") != "question_note":
            continue
        md = n.get("metadata") or {}
        if md.get("parent_question_id") is None:
            return n
    return None


def list_history(runs_dir: Path) -> list[dict[str, Any]]:
    """Enumerate completed runs on disk, newest first.

    A run is "completed" iff its directory has both notes.json and
    report.md. Directories missing either are skipped silently — those
    are crashes or abandoned runs and showing them would just be noise.
    """
    if not runs_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or not is_valid_run_id(entry.name):
            continue
        notes_path = entry / "notes.json"
        report_path = entry / "report.md"
        if not (notes_path.exists() and report_path.exists()):
            continue
        try:
            notes = json.loads(notes_path.read_text())
            root = _root_question(notes)
            if root is None:
                continue
            query = root.get("description") or root.get("title") or ""
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "run_id": entry.name,
                "query": query,
                "started_at": _started_at(entry.name).isoformat(),
            }
        )
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out


def read_notes(runs_dir: Path, run_id: str) -> list[dict[str, Any]] | None:
    """Load notes.json for a run. Returns None if missing/invalid."""
    if not is_valid_run_id(run_id):
        return None
    path = runs_dir / run_id / "notes.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def read_report_md(runs_dir: Path, run_id: str) -> str | None:
    if not is_valid_run_id(run_id):
        return None
    path = runs_dir / run_id / "report.md"
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None


def _read_token_usage(runs_dir: Path, run_id: str) -> dict[str, Any]:
    path = runs_dir / run_id / "token_usage.json"
    if not path.exists():
        return {"per_model": {}, "grand_totals": {}}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"per_model": {}, "grand_totals": {}}


def summarize(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """Build a summary payload shaped like /api/run/{run_id}/summary.

    Mirrors the live endpoint in app.py so the frontend's renderSummary()
    works unchanged. Fields that require live scheduler state (duration,
    task count) are reported as None/0.
    """
    if not is_valid_run_id(run_id):
        return None
    notes = read_notes(runs_dir, run_id)
    if notes is None:
        return None
    root = _root_question(notes)
    query = (root.get("description") or root.get("title") or "") if root else ""

    notes_by_type: dict[str, int] = {}
    sources_by_state: dict[str, int] = {}
    questions_by_status: dict[str, int] = {"OPEN": 0, "IN_PROGRESS": 0, "SYNTHESIZED": 0}
    for note in notes:
        t = note.get("type", "")
        notes_by_type[t] = notes_by_type.get(t, 0) + 1
        md = note.get("metadata") or {}
        st = md.get("state")
        if st:
            sources_by_state[str(st)] = sources_by_state.get(str(st), 0) + 1
        status = md.get("status")
        if status in questions_by_status:
            questions_by_status[status] += 1

    return {
        "run_id": run_id,
        "query": query,
        "finished": True,
        "started_at": _started_at(run_id).isoformat(),
        "finished_at": None,
        "duration_s": None,
        "report_note_id": root.get("id") if root else None,
        "tokens": _read_token_usage(runs_dir, run_id),
        "notes_by_type": notes_by_type,
        "sources_by_state": sources_by_state,
        "questions_by_status": questions_by_status,
        "tasks": 0,
        "notes_total": len(notes),
    }
