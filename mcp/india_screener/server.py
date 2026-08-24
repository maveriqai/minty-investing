"""Minty india_screener MCP server (Layer 2) — Screener.in-sourced fundamentals.

Fills a real gap in `india_price.get_fundamentals`: yfinance returns null
ROE/current-ratio for entire sectors (see #9, docs/screener-integration-
design.md §1). Screener.in has richer, already-trusted ROE/ROCE figures —
this server scrapes them directly rather than computing a third, Minty-
invented estimate that would compete with a number users already
cross-check against (§2).

`india_price.get_fundamentals` and this tool stay two single-source tools
by design (§11) — skill instructions decide precedence explicitly, they are
not merged into one multi-source call. `roe_pct` here is deliberately NOT
the same field name as `india_price`'s `return_on_equity_pct`: §2
established these are genuinely different numbers by methodology (up to
5.4pp apart on the same company), so unifying the field name would imply an
interchangeability that isn't true.

Anonymous, default-on, no auth/opt-in step (§5, §6, §11) — same model
`india_price`/`india_filings` already use against Yahoo/NSE. All fetching
goes through mcp/common/screener_fetch.py (5s/request throttle, byte-exact
cache, circuit breaker, blocked-response detection) and parsing through
mcp/common/screener_parse.py (fail-loud on a markup shape it didn't expect,
soft None on genuine data absence) — never call screener.in directly here.

Screener has no official API and no published rate-limit/markup-stability
contract (§5). This may silently stop returning some fields if Screener
changes their page layout — no CI or scheduled job can catch that before it
breaks a real run (§11's maintenance-burden acknowledgment). If a field
comes back wrong or missing, treat it as "Screener's markup may have
changed, report it" — not as a bug in your account or query.

Every tool returns {"source", "as_of", "data"} so outputs are
provenance-ready (CLAUDE.md Non-Negotiable Product Rules). source is
"screener.in (scraped)" — the parenthetical is a deliberate grounding
signal that this isn't a primary-source API the way "NSE corporate-
announcements" or "yfinance" are.
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import screener_fetch
import screener_parse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("india_screener")

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "screener.in (scraped)"


def _envelope(data: Any) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def get_fundamentals(symbol: str) -> dict[str, Any]:
    """Screener.in-sourced valuation/profitability ratios for one NSE-listed equity.

    symbol: NSE trading symbol, e.g. "APOLLOTYRE" — a trailing ".NS"/".BO"
    (india_price's own suffix convention) is stripped if present, since
    Screener's own company-page slug never carries one. Fetches the
    consolidated page first; if its financial tables are empty (a company
    with no subsidiaries — Screener still serves a 200, just with a blank
    scaffold), falls back to the standalone page automatically (§8, §11).
    The response's
    `consolidation` field always says which basis was actually used —
    "consolidated" or "standalone (no consolidated data available)" —
    never a silent substitution.

    Includes both the current ROCE/ROE and the 10/5/3-year/last-year ROE
    trend, which `india_price.get_fundamentals` doesn't have at all. Keep
    `roe_pct` separate from `india_price`'s `return_on_equity_pct` when
    narrating both — they are genuinely different numbers by methodology,
    not a rounding nuance (see this server's module docstring).

    Screener has no published API or markup-stability contract — a field
    coming back wrong or missing may mean their page layout changed, not a
    bug in this call. `data.error` is set (never a crash) if the fetch was
    blocked, the circuit breaker is open, or the page's shape didn't match
    what the parser expected.
    """
    slug = symbol.strip().upper().removesuffix(".NS").removesuffix(".BO")
    try:
        consolidated_html = screener_fetch.screener_get(f"/company/{slug}/consolidated/")
        if screener_parse.has_financial_data(consolidated_html):
            fundamentals = screener_parse.parse_fundamentals(
                slug, consolidated_html, consolidation="consolidated"
            )
        else:
            standalone_html = screener_fetch.screener_get(f"/company/{slug}/")
            fundamentals = screener_parse.parse_fundamentals(
                slug, standalone_html, consolidation="standalone (no consolidated data available)"
            )
    except RuntimeError as exc:
        # Covers ScreenerBlockedError / ScreenerCircuitOpenError
        # (screener_fetch.py) and ScreenerParseError (screener_parse.py) —
        # all three subclass RuntimeError. Never crash the tool call on a
        # fetch or parse failure, same pattern as india_price.get_fundamentals.
        return _envelope({"symbol": slug, "error": str(exc)})

    return _envelope({"symbol": slug, **asdict(fundamentals)})


mcp.tool()(get_fundamentals)


if __name__ == "__main__":
    mcp.run()
