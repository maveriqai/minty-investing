"""Minty india_macro MCP server (Layer 2, Phase 1 step 4).

RBI policy rates and NSE's trading-holiday/expiry calendar — closes out the
Layer 2 server trio started with india_price (step 1) and india_filings
(step 3).

Endpoint coverage verified live 2026-07-08:
- get_exchange_holidays / get_expiry_calendar: NSE's /api/holiday-master via
  mcp/common/exchange_calendar.py, shared with india_price's
  get_market_status (see that module's docstring) so the two servers can't
  disagree on what "today is a holiday" means.
- get_policy_rates: RBI's public "current rates" page
  (website.rbi.org.in/web/rbi/-/current-rates). RBI does not publish these
  as JSON, so this scrapes a stable HTML table (Policy Rates + Reserve
  Ratios accordions). Verified live: Policy Repo Rate, Standing Deposit
  Facility Rate, Marginal Standing Facility Rate, Bank Rate, Fixed Reverse
  Repo Rate, CRR, SLR.

Deliberately NOT implemented (no free, stable, keyless source found as of
2026-07-08 — same "honest gap, not a guess" policy as india_filings'
documented bulk/block-deals outage):
- MPC meeting-date calendar — RBI's monetary-policy calendar pages tried
  did not resolve; revisit if a real source turns up.
- MOSPI CPI/WPI series — published as monthly PDF press releases, not
  JSON/HTML; data.gov.in has an open API for some series but requires a
  registered API key, which conflicts with Minty's Phase-1 "a Claude
  subscription is the only API needed" stance (same category as the paid
  feeds CLAUDE.md already flags as deliberate later upgrades, not Phase-1
  requirements).

Every tool returns {"source", "as_of", "data"}. No money math here.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import exchange_calendar  # noqa: E402
import rbi_fetch  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("india_macro")

IST = ZoneInfo("Asia/Kolkata")

RATE_ROW_RE = re.compile(r"<th[^>]*>\s*([^<]+?)\s*</th>\s*<td[^>]*>\s*:\s*([^<]+?)\s*</td>", re.S)


def _envelope(data: Any, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def _parse_policy_rates(html: str) -> dict[str, str]:
    """Extract the Policy Rates + Reserve Ratios rows from RBI's current-rates page.

    Bounded to the section between the "Policy Rates" and "Exchange Rates"
    accordion headings so FX rates (a different concern) never leak in.
    """
    start = html.find("Policy&nbsp; Rates")
    end = html.find("Exchange &nbsp;Rates")
    section = html[start:end] if start != -1 and end != -1 else html
    return {label.strip(): value.strip() for label, value in RATE_ROW_RE.findall(section)}


def get_policy_rates() -> dict[str, Any]:
    """Current RBI key policy rates and reserve ratios (%).

    Fields (when parsing succeeds): Policy Repo Rate, Standing Deposit
    Facility Rate, Marginal Standing Facility Rate, Bank Rate, Fixed
    Reverse Repo Rate, CRR, SLR. Scraped live from RBI's own public page
    (RBI doesn't publish these as JSON) — these are committee-set rates
    that change only around bi-monthly MPC meetings, not daily, so `as_of`
    reflects when Minty fetched the page, not when RBI last changed a rate.
    For valuation risk-free rate use the 10Y G-Sec yield (a market-quoted
    yield, not this policy rate) per CLAUDE.md's India conventions — not
    fetched by this tool.
    """
    try:
        html = rbi_fetch.rbi_get_text("/web/rbi/-/current-rates")
    except Exception as exc:  # noqa: BLE001 — surfaced as a data gap, not a crash
        return _envelope({"error": str(exc)}, "RBI current-rates")
    rates = _parse_policy_rates(html)
    if not rates:
        return _envelope(
            {"error": "could not parse RBI current-rates page — layout may have changed"}, "RBI current-rates"
        )
    return _envelope(rates, "RBI current-rates")


def get_exchange_holidays(segment: str = "CM") -> dict[str, Any]:
    """NSE trading-holiday calendar for the current exchange year.

    segment: NSE's own codes — "CM" (cash/equity, default), "FO"
    (derivatives), "CD" (currency derivatives), among others NSE defines.
    Only ever covers NSE's current exchange year — there's no way to
    request a past/future year from this source (see module docstring).

    Returns a chronological list of {date ("YYYY-MM-DD"), week_day,
    description}. This is what india_price.get_market_status's
    holiday_calendar_loaded flag refers to — both tools read the same
    underlying list via mcp/common/exchange_calendar.py.
    """
    try:
        holidays = exchange_calendar.get_segment_holidays(segment)
    except Exception as exc:  # noqa: BLE001 — KeyError (bad segment) or a fetch failure, both a data gap
        return _envelope({"error": str(exc)}, "NSE holiday-master")
    return _envelope({"segment": segment.upper(), "holidays": holidays}, "NSE holiday-master")


def get_expiry_calendar(year: int, month: int) -> dict[str, Any]:
    """Monthly F&O expiry date for one calendar month — computed, not fetched.

    NSE's monthly expiry is the last Thursday of the month, pulled back to
    the preceding trading day if that Thursday is an F&O-segment holiday.
    Only reliable for NSE's current exchange year (see module docstring) —
    for other years the holiday adjustment can't be verified, so the result
    carries `holiday_adjustment_reliable: False` instead of guessing.

    Does NOT cover weekly index-derivative expiry — NSE has changed the
    weekly expiry weekday by circular more than once (e.g. moves between
    Nifty/Bank Nifty), so a hardcoded weekly rule would go stale silently;
    check NSE's current circular if you need weekly expiry.
    """
    try:
        current_year_holidays = exchange_calendar.get_segment_holidays("FO")
        reliable = any(h["date"].startswith(str(year)) for h in current_year_holidays)
    except Exception:  # noqa: BLE001 — can't confirm reliability if the fetch itself fails
        reliable = False
    expiry, adjusted = exchange_calendar.last_trading_day_of_month(year, month, weekday=3, segment="FO")
    return _envelope(
        {
            "year": year,
            "month": month,
            "expiry_date": expiry.isoformat(),
            "moved_from_last_thursday": adjusted,
            "holiday_adjustment_reliable": reliable,
        },
        "computed (last Thursday, NSE FO holiday-adjusted)",
    )


mcp.tool()(get_policy_rates)
mcp.tool()(get_exchange_holidays)
mcp.tool()(get_expiry_calendar)


if __name__ == "__main__":
    mcp.run()
