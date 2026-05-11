"""Shared HTTP helpers for retrieval clients.

The Brave and Semantic Scholar clients both need identical 429-retry
behavior: honor `Retry-After`, apply an exponential backoff floor,
cap total wait so a genuinely exhausted plan doesn't stall the run.
This module hosts that loop plus the shared policy constants.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .rate_limit import TokenBucket

logger = logging.getLogger(__name__)

MAX_429_RETRIES = 3
MAX_429_TOTAL_WAIT_S = 20.0
DEFAULT_429_BACKOFF_S = 2.0


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header value in seconds.

    HTTP also allows an HTTP-date form, but Brave and S2 both emit
    numeric seconds. Returns None on anything unparseable so the
    caller can fall back to the exponential-backoff floor.
    """
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def request_with_429_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict,
    headers: dict,
    bucket: TokenBucket,
    log_label: str,
    log_key: str,
    timeout: float,
) -> httpx.Response:
    """GET `url` under `bucket`, retrying on 429 up to MAX_429_RETRIES.

    Returns the final response. Non-2xx responses (including a
    terminal 429 after retries exhausted or wait-cap hit) are
    returned to the caller for provider-specific error shaping;
    connection errors propagate as httpx.HTTPError.
    """
    total_wait = 0.0
    attempt = 0
    while True:
        await bucket.acquire()
        resp = await client.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 429 and attempt < MAX_429_RETRIES:
            retry_after = parse_retry_after(resp.headers.get("retry-after"))
            backoff = DEFAULT_429_BACKOFF_S * (2**attempt)
            wait = max(retry_after or 0.0, backoff)
            if total_wait + wait > MAX_429_TOTAL_WAIT_S:
                logger.warning(
                    "%s_429_wait_cap %s total_wait=%.1f cap=%.1f - giving up",
                    log_label,
                    log_key,
                    total_wait + wait,
                    MAX_429_TOTAL_WAIT_S,
                )
                return resp
            logger.info(
                "%s_429_retry attempt=%d wait_s=%.1f retry_after=%s %s",
                log_label,
                attempt + 1,
                wait,
                resp.headers.get("retry-after"),
                log_key,
            )
            await asyncio.sleep(wait)
            total_wait += wait
            attempt += 1
            continue
        return resp
