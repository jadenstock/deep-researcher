"""Logfire instrumentation.

Call `setup_logfire(local)` once at startup. No-op if no token is
configured - the rest of the system runs without Logfire, traces just
go nowhere.

When Logfire rejects the token server-side (401), the OpenTelemetry OTLP
exporter retries on every span batch and spams the terminal with
"Failed to export span batch code: 401". We silence those loggers here
since they're actionable only by regenerating the token, and the user
already saw the one-time warning.
"""

from __future__ import annotations

import logging
import warnings

from .config import LocalConfig

logger = logging.getLogger(__name__)

_CONFIGURED = False

_NOISY_LOGGERS = ("pdfminer", "pypdf", "httpcore", "httpx", "urllib3", "trafilatura")


def silence_noisy_loggers() -> None:
    """Pin third-party libraries at WARNING; their DEBUG streams drown real errors."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _silence_otel_and_logfire_noise() -> None:
    """Mute OTEL exporter retry errors + logfire's per-export UserWarnings.

    Called whether or not setup succeeds - if the token is bad, both
    channels will produce noise and there's nothing the caller can do
    beyond regenerating the token.
    """
    for name in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # logfire emits "Logfire API returned status code 401" as a UserWarning.
    warnings.filterwarnings(
        "ignore",
        message=r".*Logfire API returned status code.*",
        category=UserWarning,
    )


def setup_logfire(local: LocalConfig, service_name: str = "deep-research-agent") -> bool:
    """Configure Logfire + instrument PydanticAI and httpx.

    Returns True when instrumentation was set up, False when skipped.
    Safe to call multiple times - subsequent calls are no-ops.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return True

    token = local.observability.logfire_token
    if not token:
        logger.info("logfire token not set; skipping instrumentation")
        _silence_otel_and_logfire_noise()
        return False

    import logfire

    logfire.configure(token=token, service_name=service_name)
    logfire.instrument_pydantic_ai()
    logfire.instrument_httpx()
    _silence_otel_and_logfire_noise()
    _CONFIGURED = True
    logger.info("logfire instrumented service_name=%s", service_name)
    return True
