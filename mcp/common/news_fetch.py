"""Shared news-search fetch layer — throttled GET + RSS parse for Google News.

No free NSE/RBI-style JSON news API exists, so this hits Google News' public
RSS search endpoint (keyless, no registration) — the same "a Claude
subscription is the only API needed" stance as the rest of Layer 2. Mirrors
rbi_fetch.py's throttle/retry/circuit-breaker shape (CLAUDE.md's "be polite
to data sources" rule) rather than nse_fetch.py's — Google News RSS doesn't
need a cookie warm-up the way nseindia.com does.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

BASE = "https://news.google.com"
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


class NewsCircuitOpenError(RuntimeError):
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


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""
        source_el = item.find("source")
        publisher = source_el.text if source_el is not None else None
        items.append(
            {
                "title": title,
                "link": link,
                "published": pub_date,
                "publisher": publisher,
            }
        )
    return items


def news_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Google News RSS for `query`, India-localized, with throttling, one retry, circuit breaker.

    Returns up to `limit` items of {"title", "link", "published", "publisher"}
    — headlines and links only, never full article text. Raises
    NewsCircuitOpenError if recent failures tripped the breaker, or
    RuntimeError on failure after retrying — callers should treat either as
    "this source is currently unavailable," not retry in their own loop.
    """
    global _consecutive_failures, _circuit_open_until
    if time.monotonic() < _circuit_open_until:
        raise NewsCircuitOpenError(
            f"News circuit open after {MAX_CONSECUTIVE_FAILURES} consecutive failures — retry later"
        )

    path = f"/rss/search?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            _throttle()
            resp = client.get(BASE + path)
            resp.raise_for_status()
            items = _parse_rss(resp.text)
            _consecutive_failures = 0
            return items[:limit]
        except Exception as exc:  # noqa: BLE001 — HTTP errors/timeouts/parse failures all mean "retry once, then give up"
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))

    _consecutive_failures += 1
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_S
    raise RuntimeError(f"News search failed for query '{query}': {last_exc}") from last_exc
