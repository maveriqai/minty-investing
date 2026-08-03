"""Shared NSE fetch layer — cookie bootstrap, throttling, backoff, circuit breaker.

CLAUDE.md's "be polite to data sources" rule: all NSE/BSE fetching goes
through a cached, rate-limited fetcher (>=2s/host, backoff, circuit breaker)
"once mcp/common/ lands" — it has, so india_filings (and anything NSE-facing
after it) calls `nse_get()` here rather than hitting nseindia.com with raw
httpx per server.

NSE's JSON API rejects requests without a warm session cookie first (a plain
GET to nseindia.com), and applies its own bot mitigation on top — this module
warms cookies before each call and retries once on failure before giving up,
rather than hammering the endpoint.

Same import-collision note as mcp/common/instruments.py: the top-level `mcp/`
directory shadows the installed `mcp` PyPI package, so import this the way
tests/test_india_price.py imports server.py — `sys.path.insert(0,
"<repo-root>/mcp/common")` then `import nse_fetch`.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

BASE = "https://www.nseindia.com"
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


class NSECircuitOpenError(RuntimeError):
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


def nse_get(path: str, params: dict[str, Any] | None = None, referer: str = BASE + "/") -> Any:
    """GET an NSE JSON API path with cookie warm-up, throttling, one retry, circuit breaker.

    `path` is the API path (e.g. "/api/corporate-announcements"). `referer`
    should be the human-facing NSE report page for that data, since NSE's bot
    mitigation checks it. Raises NSECircuitOpenError if recent failures
    tripped the breaker, or RuntimeError on a fetch failure after retrying —
    callers should treat either as "this data source is currently
    unavailable," not retry in their own loop.
    """
    global _consecutive_failures, _circuit_open_until
    if time.monotonic() < _circuit_open_until:
        raise NSECircuitOpenError(
            f"NSE circuit open after {MAX_CONSECUTIVE_FAILURES} consecutive failures — retry later"
        )

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            _throttle()
            client.get(referer)  # warm session cookie
            _throttle()
            resp = client.get(BASE + path, params=params, headers={"Accept": "application/json", "Referer": referer})
            resp.raise_for_status()
            data = resp.json()
            _consecutive_failures = 0
            return data
        except Exception as exc:  # noqa: BLE001 — HTTP errors, timeouts, bad JSON all mean "retry once, then give up"
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))

    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
    raise RuntimeError(f"NSE fetch failed for {path}: {last_exc}") from last_exc
