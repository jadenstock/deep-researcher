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

from ..run_artifacts import summarize_notes

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


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def list_history(runs_dir: Path) -> list[dict[str, Any]]:
    """Enumerate completed runs on disk, newest first.

    A run is "completed" iff its directory has both notes.json and
    report.md. Directories missing either are skipped silently — those
    are crashes or abandoned runs and showing them would just be noise.

    Prefers `run_summary.json` for the index entry when present (cheap
    read); falls back to parsing `notes.json` for runs that predate
    the summary file.
    """
    if not runs_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or not is_valid_run_id(entry.name):
            continue
        if not ((entry / "notes.json").exists() and (entry / "report.md").exists()):
            continue

        summary = _read_json(entry / "run_summary.json")
        if isinstance(summary, dict):
            out.append(
                {
                    "run_id": entry.name,
                    "query": summary.get("query", ""),
                    "started_at": summary.get("started_at") or _started_at(entry.name).isoformat(),
                }
            )
            continue

        # Legacy fallback: parse notes.json to find the root question.
        notes = _read_json(entry / "notes.json")
        if not isinstance(notes, list):
            continue
        root = _root_question(notes)
        if root is None:
            continue
        out.append(
            {
                "run_id": entry.name,
                "query": root.get("description") or root.get("title") or "",
                "started_at": _started_at(entry.name).isoformat(),
            }
        )
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out


def read_notes(runs_dir: Path, run_id: str) -> list[dict[str, Any]] | None:
    """Load notes.json for a run. Returns None if missing/invalid."""
    if not is_valid_run_id(run_id):
        return None
    notes = _read_json(runs_dir / run_id / "notes.json")
    return notes if isinstance(notes, list) else None


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
    data = _read_json(runs_dir / run_id / "token_usage.json")
    if isinstance(data, dict):
        return data
    return {"per_model": {}, "grand_totals": {}}


def summarize(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    """Build a summary payload shaped like /api/run/{run_id}/summary.

    Prefers `run_summary.json` when present (written by
    persist_run_artifacts). Falls back to reconstructing the payload
    from notes.json for runs that predate the summary file.
    """
    if not is_valid_run_id(run_id):
        return None

    precomputed = _read_json(runs_dir / run_id / "run_summary.json")
    if isinstance(precomputed, dict):
        return precomputed

    notes = read_notes(runs_dir, run_id)
    if notes is None:
        return None
    root = _root_question(notes)
    query = (root.get("description") or root.get("title") or "") if root else ""
    return {
        "run_id": run_id,
        "query": query,
        "finished": True,
        "started_at": _started_at(run_id).isoformat(),
        "finished_at": None,
        "duration_s": None,
        "report_note_id": root.get("id") if root else None,
        "tokens": _read_token_usage(runs_dir, run_id),
        **summarize_notes(notes),
        "tasks": 0,
        "notes_total": len(notes),
    }
