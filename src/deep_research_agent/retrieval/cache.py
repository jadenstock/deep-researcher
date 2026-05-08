"""Disk cache for retrieval calls.

Keyed on `(tool, args_hash, day_bucket)` so the same search or fetch on
the same day hits the cache, while tomorrow gets a fresh call. Tunable
if staleness tolerance changes.

This is not a fetch deduplicator — it's a replay enabler. `dra replay
<run_id>` reads from this cache without network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import diskcache


class RetrievalCache:
    def __init__(self, directory: Path | str) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(d))

    def get(self, tool: str, args: dict[str, Any]) -> Any | None:
        return self._cache.get(self._key(tool, args))

    def set(self, tool: str, args: dict[str, Any], value: Any) -> None:
        self._cache[self._key(tool, args)] = value

    def close(self) -> None:
        self._cache.close()

    def __enter__(self) -> RetrievalCache:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _key(tool: str, args: dict[str, Any]) -> str:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        blob = json.dumps(args, sort_keys=True, default=str)
        args_hash = hashlib.md5(blob.encode()).hexdigest()[:16]
        return f"{tool}:{args_hash}:{day}"
