"""Shared NSE trading-holiday calendar.

Single source of truth for "is this date an NSE holiday?" so india_price's
get_market_status and india_macro's get_exchange_holidays/get_expiry_calendar
can't drift on the answer. Built on nse_fetch (inherits its throttling and
circuit breaker) rather than a second, separate NSE client.

NSE's /api/holiday-master only ever returns the current exchange year's
list (verified 2026-07-08: a July request still returned January dates for
the same year, so it's a full-year list, not "remaining holidays") — there
is no way to ask it for a past or future year. Cached in-process for
CACHE_TTL_S since a year's holiday list changes rarely, not per-request.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nse_fetch  # noqa: E402

REFERER = "https://www.nseindia.com/resources/exchange-communication-holidays"
CACHE_TTL_S = 6 * 3600.0

_cache: dict[str, Any] = {"fetched_at": 0.0, "raw": None}


def _fetch_raw() -> dict[str, Any]:
    now = time.monotonic()
    if _cache["raw"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_S:
        return _cache["raw"]
    raw = nse_fetch.nse_get("/api/holiday-master", params={"type": "trading"}, referer=REFERER)
    _cache["raw"], _cache["fetched_at"] = raw, now
    return raw


def get_segment_holidays(segment: str = "CM") -> list[dict[str, str]]:
    """Holiday list for one NSE segment, normalized to ISO dates, chronological.

    segment: NSE's own codes, e.g. "CM" (cash/equity, default), "FO"
    (derivatives), "CD" (currency derivatives). Raises KeyError if `segment`
    isn't one NSE returned this call — inspect the exception's known-segments
    list rather than guessing a code. Raises whatever nse_fetch.nse_get
    raises (RuntimeError, nse_fetch.NSECircuitOpenError) on fetch failure.
    """
    raw = _fetch_raw()
    if segment not in raw:
        raise KeyError(f"unknown segment '{segment}', known: {sorted(raw)}")
    out = []
    for row in raw[segment]:
        d = datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        out.append({"date": d.isoformat(), "week_day": row.get("weekDay"), "description": row.get("description")})
    out.sort(key=lambda r: r["date"])
    return out


def is_trading_holiday(date_iso: str, segment: str = "CM") -> bool:
    """True if `date_iso` ("YYYY-MM-DD") is an NSE holiday for `segment`.

    Fails open (returns False) on any fetch/parse error — a holiday-calendar
    outage should degrade to "assume a normal trading day," not break a
    market-status check that used to work with zero network dependency.
    """
    try:
        return any(h["date"] == date_iso for h in get_segment_holidays(segment))
    except Exception:
        return False


def last_trading_day_of_month(year: int, month: int, weekday: int, segment: str = "FO") -> tuple[date, bool]:
    """Last occurrence of `weekday` (Mon=0..Sun=6) in the month, pulled back over holidays.

    Used for NSE's monthly F&O expiry (last Thursday, weekday=3), which
    moves to the preceding trading day when that Thursday is a holiday.
    Returns (date, was_adjusted). Only reliable for the current exchange
    year (see module docstring) — callers should check that before trusting
    the holiday adjustment for other years.
    """
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    d = next_month_first
    d -= timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    original = d
    while d.weekday() >= 5 or is_trading_holiday(d.isoformat(), segment):
        d -= timedelta(days=1)
    return d, d != original
