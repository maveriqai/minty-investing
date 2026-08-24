"""Shared Screener.in fetch layer — throttling, backoff, circuit breaker, cache.

See docs/screener-integration-design.md §7 for the full rationale. Screener
has no published API or rate-limit contract and is a paid product being
scraped rather than an API being politely wrapped, so this is more
conservative than mcp/common/nse_fetch.py's 2s/host floor: 5s/request, plus
a byte-exact per-path HTML cache (a full company page is a much heavier
fetch than NSE's narrow JSON calls, worth reusing across a run) and explicit
blocked-response detection so a Screener-side block surfaces as a distinct,
diagnosable error rather than a generic failure.

Same import-collision note as nse_fetch.py: import this the way
tests/test_nse_fetch.py imports nse_fetch — `sys.path.insert(0,
"<repo-root>/mcp/common")` then `import screener_fetch`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

BASE = "https://www.screener.in"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MIN_INTERVAL_S = 5.0  # deliberately > NSE's 2s floor — see module docstring
MAX_CONSECUTIVE_FAILURES = 3
CIRCUIT_COOLDOWN_S = 120.0

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "screener_cache"

_client: httpx.Client | None = None
_last_request_at: float = 0.0
_consecutive_failures: int = 0
_circuit_open_until: float = 0.0

# Markers observed on generic anti-bot/captcha challenge pages (Cloudflare
# and similar) — a real Screener block hasn't been seen yet (§6), so this is
# a best-effort net cast wide enough to catch one if it starts happening.
_BLOCK_MARKERS = ("captcha", "access denied", "rate limit", "too many requests")

# Matches the two company-page paths this doc's scope actually fetches:
# "/company/<slug>/consolidated/" and "/company/<slug>/".
_COMPANY_PATH_RE = re.compile(r"^/company/([^/]+)/(consolidated/)?$")


class ScreenerBlockedError(RuntimeError):
    """Screener returned a 403/429 or an obvious captcha page — anonymous
    access may have stopped working. See the Screener.in integration
    design doc's "Anonymous access" section (§6) for the auth fallback plan."""


class ScreenerCircuitOpenError(RuntimeError):
    """Repeated recent failures tripped the breaker — don't retry in a loop."""


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    return _client


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()


def _is_blocked_response(status_code: int, html: str) -> bool:
    """True if a response looks like an anti-bot block rather than a real page.

    Kept as a small pure function, separate from the actual HTTP call, so
    it's directly testable against fixtures without mocking a network
    client (§7).
    """
    if status_code in (403, 429):
        return True
    lowered = html.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _cache_path_for(path: str) -> Path:
    """Byte-exact cache path for a company page path, keyed by symbol + basis.

    e.g. "/company/APOLLOTYRE/consolidated/" -> APOLLOTYRE_consolidated.html,
    "/company/APOLLOTYRE/" -> APOLLOTYRE_standalone.html — matching the URL
    actually requested, not whichever basis the page turns out to have, so
    the two legs of the consolidated/standalone fallback (§8) each cache
    under their own unambiguous path.
    """
    match = _COMPANY_PATH_RE.match(path)
    if not match:
        raise ValueError(f"unrecognized screener path for caching: {path!r}")
    symbol, consolidated = match.group(1), match.group(2)
    basis = "consolidated" if consolidated else "standalone"
    return CACHE_DIR / f"{symbol}_{basis}.html"


def _is_fresh(path: Path, ttl_hours: float) -> bool:
    """True if `path` exists and was written within `ttl_hours`.

    mtime is the fetched-at stamp, no sidecar metadata needed. ttl_hours <= 0
    disables the cache (always refetch) — same convention as nse_fetch.py.
    """
    if ttl_hours <= 0 or not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < ttl_hours


def screener_get(path: str, *, use_cache: bool = True, cache_ttl_hours: float = 24.0) -> str:
    """GET a screener.in company page, throttled, one retry, byte-exact cached.

    `path` must be a company page path this module knows how to cache —
    "/company/<slug>/consolidated/" or "/company/<slug>/". Returns raw HTML.
    Raises ScreenerBlockedError if the response looks like a block
    (403/429/captcha marker) — not retried, since retrying against a block is
    pointless and only risks making it worse. Raises ScreenerCircuitOpenError
    if recent failures tripped the breaker, or RuntimeError on any other
    fetch failure after retrying once.
    """
    global _consecutive_failures, _circuit_open_until

    cache_path = _cache_path_for(path)
    if use_cache and _is_fresh(cache_path, cache_ttl_hours):
        return cache_path.read_text()

    if time.monotonic() < _circuit_open_until:
        raise ScreenerCircuitOpenError(
            f"Screener circuit open after {MAX_CONSECUTIVE_FAILURES} consecutive failures — retry later"
        )

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(2):
        _throttle()
        try:
            resp = client.get(BASE + path)
        except Exception as exc:  # noqa: BLE001 — network errors mean "retry once, then give up"
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
            continue

        if _is_blocked_response(resp.status_code, resp.text):
            _consecutive_failures += 1
            if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
            raise ScreenerBlockedError(
                f"Screener appears to be blocking anonymous requests to {path} "
                f"(status {resp.status_code}) — see the Screener.in integration "
                "design doc's \"Anonymous access\" section (§6) for the auth fallback plan."
            )

        try:
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
            continue

        _consecutive_failures = 0
        html = resp.text
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html)  # byte-exact (text) cache
        return html

    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
    raise RuntimeError(f"Screener fetch failed for {path}: {last_exc}") from last_exc
