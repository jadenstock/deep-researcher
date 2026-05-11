"""Per-run artifact persistence.

Shared by both entry points (CLI `research` subcommand and the
server's `run_session`). Writes the main dump (notes.json, report.md,
optional report.json, optional run_summary.json) in parallel. Token
usage is NOT included so callers can save it independently - even if
the main dump fails, a token_usage.json on disk is still useful.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas.enums import QuestionStatus
from .schemas.note import Note


def summarize_notes(notes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Count notes by type / source state / question status.

    Operates on serialized note dicts (the on-disk form). Live callers
    pass `note.model_dump(mode="json")`. Returns the three counter
    dicts used by the `/api/run/{run_id}/summary` and
    `/api/history/{run_id}/summary` payloads.
    """
    notes_by_type: dict[str, int] = {}
    sources_by_state: dict[str, int] = {}
    questions_by_status: dict[str, int] = {s.value: 0 for s in QuestionStatus}
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
        "notes_by_type": notes_by_type,
        "sources_by_state": sources_by_state,
        "questions_by_status": questions_by_status,
    }


def build_run_summary(
    *,
    run_id: str,
    query: str,
    started_at: datetime,
    finished_at: datetime | None,
    report_note_id: str | None,
    notes: Iterable[Note],
    tokens: dict[str, Any],
) -> dict[str, Any]:
    """Build the run-summary payload matching `/api/run/{run_id}/summary`.

    Persisting this alongside notes.json lets `history.list_history`
    and `history.summarize` skip reparsing the full notes graph on
    every request.
    """
    note_dicts = [n.model_dump(mode="json") for n in notes]
    duration_s = (finished_at - started_at).total_seconds() if finished_at else None
    return {
        "run_id": run_id,
        "query": query,
        "finished": True,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat() if finished_at else None,
        "duration_s": duration_s,
        "report_note_id": report_note_id,
        "tokens": tokens,
        **summarize_notes(note_dicts),
        # Tasks count is a live-only concept (comes from event history);
        # 0 on disk keeps the payload shape consistent with the history
        # endpoint where tasks aren't available either.
        "tasks": 0,
        "notes_total": len(note_dicts),
    }


async def persist_run_artifacts(
    run_dir: Path,
    *,
    notes: Iterable[Note],
    report_markdown: str,
    report_json: dict | None,
    summary: dict | None = None,
) -> None:
    """Write notes.json, report.md, and optionally report.json /
    run_summary.json in parallel.

    `report_json` is None for partial/failed runs where no structured
    ResearcherReport exists. `summary` is omitted only for callers
    that don't need a disk-history index entry.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    notes_out = [n.model_dump(mode="json") for n in notes]
    writes: list[tuple[Path, str]] = [
        (run_dir / "notes.json", json.dumps(notes_out, indent=2, default=str)),
        (run_dir / "report.md", report_markdown),
    ]
    if report_json is not None:
        writes.append((run_dir / "report.json", json.dumps(report_json, indent=2, default=str)))
    if summary is not None:
        writes.append((run_dir / "run_summary.json", json.dumps(summary, indent=2, default=str)))
    await asyncio.gather(*(asyncio.to_thread(path.write_text, content) for path, content in writes))
