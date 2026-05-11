"""Generate run ids shared by CLI and server."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"
