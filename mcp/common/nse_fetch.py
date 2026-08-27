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

`nse_get_binary` is the same discipline for binary documents (filing PDFs) —
added for issue #25, where the model reached for raw Bash+curl to fetch a
filing document because no governed path existed, bypassing this module
entirely. Bash is no longer in Minty's builtin tool surface at all
(`engine/config.py`); `india_filings.get_filing_document` is the replacement.

Same import-collision note as mcp/common/instruments.py: the top-level `mcp/`
directory shadows the installed `mcp` PyPI package, so import this the way
tests/test_india_price.py imports server.py — `sys.path.insert(0,
"<repo-root>/mcp/common")` then `import nse_fetch`.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
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

# Filing documents (issue #25's get_filing_document), not JSON API calls —
# byte-exact cached like screener_fetch.py's company pages. A filed document
# never changes once submitted, so this TTL is far longer than nse_get's.
DOC_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "filing_doc_cache"
DOC_CACHE_TTL_HOURS = 24 * 30

_client: httpx.Client | None = None
_last_request_at: float = 0.0
_consecutive_failures: int = 0
_circuit_open_until: float = 0.0


class NSECircuitOpenError(RuntimeError):
    """Repeated recent failures tripped the breaker — don't retry in a loop, surface as a data gap."""


class NSEUntrustedHostError(RuntimeError):
    """`url` isn't on an NSE-owned host — refused rather than fetched, so `nse_get_binary` can't become a
    general-purpose fetch proxy for arbitrary URLs."""


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


def _is_doc_cache_fresh(path: Path, ttl_hours: float) -> bool:
    """Same convention as screener_fetch.py's `_is_fresh`: mtime is the fetched-at stamp, no sidecar
    metadata. ttl_hours <= 0 disables the cache (always refetch)."""
    if ttl_hours <= 0 or not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < ttl_hours


def _doc_cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:32]
    suffix = Path(httpx.URL(url).path).suffix or ".pdf"
    return DOC_CACHE_DIR / f"{digest}{suffix}"


def nse_get_binary(
    url: str, *, referer: str = BASE + "/", use_cache: bool = True, cache_ttl_hours: float = DOC_CACHE_TTL_HOURS
) -> bytes:
    """GET a binary document NSE served (e.g. a filing PDF from a `get_announcements` `attchmntFile`
    field) with the same throttle/circuit-breaker discipline as `nse_get`, plus a byte-exact cache.

    `url` must be an absolute https URL on an NSE-owned host (nseindia.com or any subdomain, e.g.
    nsearchives.nseindia.com — the filing-archive host) — anything else raises `NSEUntrustedHostError`
    rather than being fetched, since this exists to read documents NSE itself served, not as a general
    fetch proxy for arbitrary URLs. Raises `NSECircuitOpenError` if recent failures tripped the breaker,
    or `RuntimeError` on a fetch failure after retrying once — callers should treat either as "this
    document currently unavailable," not retry in their own loop.
    """
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or not (parsed.host == "nseindia.com" or parsed.host.endswith(".nseindia.com")):
        raise NSEUntrustedHostError(f"refusing to fetch non-NSE host: {parsed.host!r}")

    cache_path = _doc_cache_path(url)
    if use_cache and _is_doc_cache_fresh(cache_path, cache_ttl_hours):
        return cache_path.read_bytes()

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
            resp = client.get(url, headers={"Referer": referer})
            resp.raise_for_status()
            content = resp.content
            _consecutive_failures = 0
            DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
            return content
        except Exception as exc:  # noqa: BLE001 — HTTP errors, timeouts all mean "retry once, then give up"
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))

    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
    raise RuntimeError(f"NSE document fetch failed for {url}: {last_exc}") from last_exc
