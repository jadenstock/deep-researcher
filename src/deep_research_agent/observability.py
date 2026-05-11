"""Logging noise control.

Third-party libraries (pdfminer, httpx, etc.) emit verbose DEBUG/INFO
streams that drown real errors. Call `silence_noisy_loggers()` once at
startup to pin them at WARNING.
"""

from __future__ import annotations

import logging

_NOISY_LOGGERS = ("pdfminer", "pypdf", "httpcore", "httpx", "urllib3", "trafilatura")


def silence_noisy_loggers() -> None:
    """Pin third-party libraries at WARNING; their DEBUG streams drown real errors."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
