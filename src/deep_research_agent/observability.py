"""Logfire instrumentation.

Call `setup_logfire(local)` once at startup. No-op if no token is
configured — the rest of the system runs without Logfire, traces just
go nowhere.
"""

from __future__ import annotations

import logging

from .config import LocalConfig

logger = logging.getLogger(__name__)

_CONFIGURED = False


def setup_logfire(local: LocalConfig, service_name: str = "deep-research-agent") -> bool:
    """Configure Logfire + instrument PydanticAI and httpx.

    Returns True when instrumentation was set up, False when skipped.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return True

    token = local.observability.logfire_token
    if not token:
        logger.info("logfire token not set; skipping instrumentation")
        return False

    import logfire

    logfire.configure(token=token, service_name=service_name)
    logfire.instrument_pydantic_ai()
    logfire.instrument_httpx()
    _CONFIGURED = True
    logger.info("logfire instrumented service_name=%s", service_name)
    return True
