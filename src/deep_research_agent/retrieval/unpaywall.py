"""Unpaywall DOI → open-access PDF resolver.

Given a DOI, returns the best open-access PDF URL or None. Used to
rescue paywalled academic hits: S2 often gives us a DOI landing page
that's behind a paywall, but Unpaywall can surface an OA copy
(institutional repo, preprint server, publisher OA track).

Unpaywall requires a contact email in the `email` query parameter.
The default is a generic placeholder; set `local.retrieval.unpaywall_email`
in config/local.toml to override.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"

_UP_LOCK = asyncio.Lock()
_UP_LAST_CALL_AT = 0.0
_UP_MIN_INTERVAL_S = 0.3  # 100k req/day free; 0.3s keeps us well under


async def _unpaywall_throttle() -> None:
    global _UP_LAST_CALL_AT
    async with _UP_LOCK:
        wait = _UP_MIN_INTERVAL_S - (time.monotonic() - _UP_LAST_CALL_AT)
        if wait > 0:
            await asyncio.sleep(wait)
        _UP_LAST_CALL_AT = time.monotonic()


class UnpaywallClient:
    def __init__(self, email: str, timeout: float = 10.0) -> None:
        self._email = email
        self._timeout = timeout

    async def find_oa_pdf(self, doi: str) -> str | None:
        """Return the best OA PDF URL for `doi`, or None if no OA copy exists."""
        url = UNPAYWALL_URL.format(doi=doi)
        await _unpaywall_throttle()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, params={"email": self._email})
        except httpx.HTTPError as exc:
            logger.debug("unpaywall_failed doi=%s err=%s", doi, exc)
            return None
        if resp.status_code >= 400:
            logger.debug("unpaywall_non_2xx doi=%s status=%d", doi, resp.status_code)
            return None
        data = resp.json()
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url") or None
