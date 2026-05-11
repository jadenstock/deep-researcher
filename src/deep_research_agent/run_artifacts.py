"""Per-run artifact persistence.

Shared by both entry points (CLI `research` subcommand and the
server's `run_session`). Writes the main dump (notes.json, report.md,
optional report.json) in parallel. Token usage is NOT included so
callers can save it independently - even if the main dump fails, a
token_usage.json on disk is still useful.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path

from .schemas.note import Note


async def persist_run_artifacts(
    run_dir: Path,
    *,
    notes: Iterable[Note],
    report_markdown: str,
    report_json: dict | None,
) -> None:
    """Write notes.json, report.md, and optionally report.json in parallel.

    `report_json` is None for partial/failed runs where no structured
    ResearcherReport exists - only the reconstructed markdown survives.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    notes_out = [n.model_dump(mode="json") for n in notes]
    writes: list[tuple[Path, str]] = [
        (run_dir / "notes.json", json.dumps(notes_out, indent=2, default=str)),
        (run_dir / "report.md", report_markdown),
    ]
    if report_json is not None:
        writes.append((run_dir / "report.json", json.dumps(report_json, indent=2, default=str)))
    await asyncio.gather(*(asyncio.to_thread(path.write_text, content) for path, content in writes))
