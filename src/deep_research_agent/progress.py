"""Live run progress: `runs/<run_id>/progress.json` and reading it back.

`ProgressPublisher` is an `EventPublisher` that keeps a small rolling
picture of a run (phase, analyst dispatches vs budget, notes by type,
token totals, cost so far) and writes it to `progress.json` so other
processes - `dra status`, `dra wait`, a Claude skill - can watch a run
they didn't start. Writes are atomic (tmp + rename) and throttled; a
deferred flush makes sure the last event in a burst still lands.

`read_status` turns a run directory into a `RunStatus`, preferring the
final `run_summary.json` over `progress.json` and detecting runs whose
process died without finishing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agents.events import EventPublisher
from .pricing import ModelPrices, cost_usd
from .run_artifacts import summarize_notes
from .schemas.enums import AgentRunStatus, AgentType, RoleClass, TaskTier
from .schemas.note import Note

logger = logging.getLogger(__name__)

PROGRESS_FILE = "progress.json"
_MIN_WRITE_INTERVAL_S = 3.0


class ProgressPublisher(EventPublisher):
    """Track run progress from agent events and persist it to disk.

    Token usage arrives as per-agent running totals (`on_usage_progress`,
    after every agent step) and as one final total per agent
    (`on_token_usage`); both overwrite that agent's entry, so totals stay
    correct whichever arrives last.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str,
        query: str,
        analyst_budget: int,
        prices: ModelPrices,
        pid: int | None = None,
    ) -> None:
        self._path = run_dir / PROGRESS_FILE
        self._run_id = run_id
        self._query = query
        self._analyst_budget = analyst_budget
        self._prices = prices
        self._pid = pid if pid is not None else os.getpid()
        self._started_at = datetime.now(UTC)
        self._phase = "starting"
        self._finished = False
        self._ok: bool | None = None
        self._running: dict[str, AgentType] = {}
        self._done_by_type: dict[str, int] = {}
        self._analysts_dispatched = 0
        self._notes: dict[str, dict[str, Any]] = {}
        self._usage: dict[
            str, tuple[str, int, int, int]
        ] = {}  # agent_id -> (model, in, out, cached)
        self._last_event = "run starting"
        self._last_write = 0.0
        self._flush_pending = False
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write()

    # --- EventPublisher ---------------------------------------------------

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
        self._running[agent_id] = agent_type
        if agent_type == AgentType.ANALYST:
            self._analysts_dispatched += 1
        if agent_type == AgentType.LANDSCAPE:
            self._phase = "landscape"
        elif agent_type in (AgentType.ANALYST, AgentType.SCOUT) and self._phase != "finished":
            self._phase = "researching"
        self._last_event = f"{agent_type.value.lower()} started: {goal[:80]}"
        self._changed(force=True)

    def on_agent_done(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        status: AgentRunStatus,
        verdict: str,
    ) -> None:
        self._running.pop(agent_id, None)
        key = agent_type.value
        self._done_by_type[key] = self._done_by_type.get(key, 0) + 1
        self._last_event = f"{key.lower()} {status.value.lower()}"
        self._changed(force=True)

    def on_note_created(self, note: Note) -> None:
        self._notes[str(note.id)] = note.model_dump(mode="json")
        self._changed()

    def on_note_replaced(self, note: Note) -> None:
        self.on_note_created(note)

    def on_tool_start(self, *, agent_id: str, tool_call_id: str, tool: str, summary: str) -> None:
        pass

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
        pass

    def on_usage_progress(
        self,
        *,
        agent_id: str,
        agent_type: AgentType,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
    ) -> None:
        self._usage[agent_id] = (model_id, input_tokens, output_tokens, cache_read_tokens)
        self._changed()

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
        # The final per-agent total. It replaces the running snapshot
        # rather than adding to it.
        self.on_usage_progress(
            agent_id=agent_id,
            agent_type=agent_type,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )

    # --- lifecycle ----------------------------------------------------------

    def finish(self, *, ok: bool) -> None:
        self._finished = True
        self._ok = ok
        self._phase = "finished" if ok else "failed"
        self._last_event = "run finished" if ok else "run failed"
        self._write()

    # --- persistence ------------------------------------------------------

    def _changed(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_write >= _MIN_WRITE_INTERVAL_S:
            self._write()
            return
        if self._flush_pending:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write()
            return
        self._flush_pending = True
        loop.call_later(_MIN_WRITE_INTERVAL_S, self._deferred_flush)

    def _deferred_flush(self) -> None:
        self._flush_pending = False
        self._write()

    def snapshot(self) -> dict[str, Any]:
        tokens = {"input": 0, "output": 0, "cache_read": 0}
        cost: float | None = 0.0
        for model_id, inp, out, cached in self._usage.values():
            tokens["input"] += inp
            tokens["output"] += out
            tokens["cache_read"] += cached
            c = cost_usd(
                self._prices,
                model_id,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cached,
            )
            cost = None if cost is None or c is None else cost + c
        running_by_type: dict[str, int] = {}
        for t in self._running.values():
            running_by_type[t.value] = running_by_type.get(t.value, 0) + 1
        return {
            "run_id": self._run_id,
            "query": self._query[:200],
            "pid": self._pid,
            "started_at": self._started_at.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "phase": self._phase,
            "finished": self._finished,
            "ok": self._ok,
            "analysts": {"dispatched": self._analysts_dispatched, "budget": self._analyst_budget},
            "agents_running": running_by_type,
            "agents_done": dict(self._done_by_type),
            **summarize_notes(self._notes.values()),
            "tokens": tokens,
            "cost_usd": cost,
            "last_event": self._last_event,
        }

    def _write(self) -> None:
        self._last_write = time.monotonic()
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.snapshot(), indent=2, default=str))
            tmp.replace(self._path)
        except Exception:
            logger.exception("progress write failed path=%s", self._path)


# --- reading status back -----------------------------------------------------


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    state: str  # "running" | "finished" | "failed" | "crashed"
    progress: dict[str, Any]

    @property
    def done(self) -> bool:
        return self.state != "running"


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_status(run_dir: Path) -> RunStatus:
    """Classify a run from its directory.

    A finished `run_summary.json` wins: the run is over even if a stale
    progress file says otherwise. Without one, an unfinished progress
    file whose process is gone means the run crashed; no progress file
    at all means it never got going.
    """
    run_id = run_dir.name
    progress: dict[str, Any] = {}
    try:
        progress = json.loads((run_dir / PROGRESS_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        progress = {}
    summary_path = run_dir / "run_summary.json"
    if summary_path.exists():
        progress = _with_summary_fields(progress, summary_path)
        ok = progress.get("ok")
        if ok is None:
            ok = (run_dir / "report.json").exists()
        return RunStatus(run_id, "finished" if ok else "failed", progress)
    if not progress:
        return RunStatus(run_id, "failed", progress)
    if progress.get("finished"):
        return RunStatus(run_id, "finished" if progress.get("ok") else "failed", progress)
    if not _pid_alive(progress.get("pid")):
        return RunStatus(run_id, "crashed", progress)
    return RunStatus(run_id, "running", progress)


def _with_summary_fields(progress: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    """Fill gaps from the final run summary (runs from before progress
    files existed have only the summary)."""
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return progress
    merged = dict(progress)
    for key in ("questions_by_status", "sources_by_state", "started_at", "query", "cost_usd"):
        if merged.get(key) is None and summary.get(key) is not None:
            merged[key] = summary[key]
    if summary.get("finished_at"):
        merged["updated_at"] = summary["finished_at"]
    return merged


def format_status(status: RunStatus) -> str:
    """One human-readable line for `dra status` / `dra wait`."""
    p = status.progress
    parts = [f"{status.run_id} {status.state}"]
    if p.get("phase") and status.state == "running":
        parts.append(p["phase"])
    started = p.get("started_at")
    if started:
        try:
            end = datetime.fromisoformat(p.get("updated_at") or started)
            if status.state == "running":
                end = datetime.now(UTC)
            mins = (end - datetime.fromisoformat(started)).total_seconds() / 60
            parts.append(f"{mins:.0f} min")
        except ValueError:
            pass
    a = p.get("analysts") or {}
    if a:
        parts.append(f"analysts {a.get('dispatched', 0)}/{a.get('budget', '?')}")
    q = p.get("questions_by_status") or {}
    if q:
        total = sum(q.values())
        parts.append(f"questions {q.get('SYNTHESIZED', 0)}/{total} answered")
    s = p.get("sources_by_state") or {}
    if s:
        analyzed = s.get("ANALYZED", 0)
        parts.append(f"sources {analyzed} analyzed / {s.get('FETCHED', 0) + analyzed} fetched")
    cost = p.get("cost_usd")
    tok = p.get("tokens") or {}
    if cost is not None:
        cache = tok.get("cache_read", 0) / tok["input"] if tok.get("input") else 0
        parts.append(f"${cost:.2f} (cache {cache:.0%})")
    if p.get("last_event") and status.state == "running":
        parts.append(f"last: {p['last_event']}")
    return " · ".join(parts)


def find_runs(runs_dir: Path) -> list[Path]:
    """Run directories, newest first (run ids sort by timestamp)."""
    if not runs_dir.exists():
        return []
    return sorted((d for d in runs_dir.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
