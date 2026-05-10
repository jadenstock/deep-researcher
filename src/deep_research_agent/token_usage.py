"""Per-run token-usage bookkeeping.

A run touches many models - tier classifier, landscape surveyor,
decomposer, analyzers, synthesizers, verifiers, judge, validator,
report writer. Each goes through pydantic_ai which reports a
`RunUsage` on every `agent.run()`. We aggregate those counts per
model so a run summary can say "HIGH-tier model burned 40k input /
12k output across 18 calls".

Scope is intentionally per-run, not process-global: a tracker is
instantiated in runner.py / cli.py, attached to the AgentExecutor,
and used via `HandlerContext.track(agent, user)`. At end of run
we log a formatted summary and write a token_usage.json alongside
the report for later analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelTotals:
    """Running totals for a single model_id."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: int = 0
    # Task-type breakdown so you can see, e.g., that ANALYZE_SOURCE
    # dominates the call count for a given model.
    by_task_type: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "tool_calls": self.tool_calls,
            "by_task_type": dict(self.by_task_type),
        }


class TokenUsageTracker:
    """Async-safe per-model token counter for a single run.

    The lock is conservative: int increments on CPython are GIL-safe,
    but we also mutate the by_task_type dict which is not. Cheaper to
    lock on every record() than to reason about which fields are safe.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._totals: dict[str, ModelTotals] = {}

    async def record(
        self,
        model_id: str,
        usage: Any,
        task_type: str | None = None,
    ) -> dict[str, int]:
        """Record a single `agent.run()` completion.

        `usage` is a pydantic_ai RunUsage (or compatible); we read the
        fields defensively so a version bump that adds/renames fields
        won't crash the run.

        Returns the scalar deltas that were recorded (input/output/cache
        tokens) so callers can forward them to UI events without having
        to re-parse the RunUsage object.
        """
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_write_tokens", 0) or 0)
        tool_calls = int(getattr(usage, "tool_calls", 0) or 0)

        async with self._lock:
            t = self._totals.setdefault(model_id, ModelTotals())
            t.calls += 1
            t.input_tokens += input_tokens
            t.output_tokens += output_tokens
            t.cache_read_tokens += cache_read
            t.cache_write_tokens += cache_write
            t.tool_calls += tool_calls
            if task_type:
                t.by_task_type[task_type] = t.by_task_type.get(task_type, 0) + 1

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        }

    def snapshot(self) -> dict[str, ModelTotals]:
        """Return a shallow copy of per-model totals. Safe to read
        without the lock - we only swap references, never mutate in
        place after snapshot."""
        return dict(self._totals)

    def grand_totals(self) -> ModelTotals:
        """Aggregate across all models (by_task_type is summed too)."""
        agg = ModelTotals()
        for t in self._totals.values():
            agg.calls += t.calls
            agg.input_tokens += t.input_tokens
            agg.output_tokens += t.output_tokens
            agg.cache_read_tokens += t.cache_read_tokens
            agg.cache_write_tokens += t.cache_write_tokens
            agg.tool_calls += t.tool_calls
            for k, v in t.by_task_type.items():
                agg.by_task_type[k] = agg.by_task_type.get(k, 0) + v
        return agg

    def format_table(self) -> str:
        """Human-readable summary for the end-of-run log line."""
        snap = self.snapshot()
        if not snap:
            return "token usage: (no LLM calls recorded)"
        rows: list[tuple[str, int, int, int, int]] = []
        for model_id, t in sorted(snap.items()):
            rows.append((model_id, t.calls, t.input_tokens, t.output_tokens, t.total_tokens))
        grand = self.grand_totals()
        rows.append(
            ("TOTAL", grand.calls, grand.input_tokens, grand.output_tokens, grand.total_tokens)
        )

        name_w = max(len(r[0]) for r in rows)
        lines = [
            f"  {'model':<{name_w}}  {'calls':>6}  {'in':>10}  {'out':>10}  {'total':>10}",
            f"  {'-' * name_w}  {'-' * 6}  {'-' * 10}  {'-' * 10}  {'-' * 10}",
        ]
        for name, calls, in_t, out_t, total in rows:
            lines.append(f"  {name:<{name_w}}  {calls:>6}  {in_t:>10,}  {out_t:>10,}  {total:>10,}")
        return "token usage summary:\n" + "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "per_model": {model_id: t.to_dict() for model_id, t in snap.items()},
            "grand_totals": self.grand_totals().to_dict(),
        }

    def save_json(self, path: Path) -> None:
        """Write per-run usage to disk. Parent directory must exist."""
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))
        logger.info("token_usage_written path=%s", path)
