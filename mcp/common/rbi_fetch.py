"""Shared RBI HTTP fetch layer — throttled GET for RBI's public website.

RBI doesn't publish policy rates as JSON (unlike NSE's corporate-filings
API) — the only live source is the "current rates" HTML page
(website.rbi.org.in/web/rbi/-/current-rates), so india_macro scrapes a
stable table out of it. This module mirrors nse_fetch.py's throttle/retry/
circuit-breaker shape for the same "be polite to data sources" reason
(CLAUDE.md), but is simpler: RBI's site doesn't require a cookie warm-up
GET before the real request the way nseindia.com does.
"""

from __future__ import annotations

import time

import httpx

BASE = "https://website.rbi.org.in"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MIN_INTERVAL_S = 2.0  # CLAUDE.md: >=2s/host
MAX_CONSECUTIVE_FAILURES = 3
CIRCUIT_COOLDOWN_S = 120.0

_client: httpx.Client | None = None
_last_request_at: float = 0.0
_consecutive_failures: int = 0
_circuit_open_until: float = 0.0


class RBICircuitOpenError(RuntimeError):
    """Repeated recent failures tripped the breaker — don't retry in a loop, surface as a data gap."""


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=30,
            follow_redirects=True,
        )
    return _client


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()


def rbi_get_text(path: str) -> str:
    """GET an RBI page and return raw HTML, with throttling, one retry, circuit breaker.

    `path` is appended to BASE (e.g. "/web/rbi/-/current-rates"). Raises
    RBICircuitOpenError if recent failures tripped the breaker, or
    RuntimeError on failure after retrying — callers should treat either as
    "this source is currently unavailable," not retry in their own loop.
    """
    global _consecutive_failures, _circuit_open_until
    if time.monotonic() < _circuit_open_until:
        raise RBICircuitOpenError(
            f"RBI circuit open after {MAX_CONSECUTIVE_FAILURES} consecutive failures — retry later"
        )

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            _throttle()
            resp = client.get(BASE + path)
            resp.raise_for_status()
            _consecutive_failures = 0
            return resp.text
        except Exception as exc:  # noqa: BLE001 — HTTP errors/timeouts all mean "retry once, then give up"
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))

    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
    raise RuntimeError(f"RBI fetch failed for {path}: {last_exc}") from last_exc
