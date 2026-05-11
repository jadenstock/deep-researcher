"""Time helpers shared across layers (schemas, agents, server)."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
