"""Minty india_filings MCP server (Layer 2, Phase 1 step 3).

Corporate filings, ownership, and market-wide flow/surveillance data from
NSE's public JSON API — company announcements, shareholding patterns,
FII/DII flows, and ASM/GSM surveillance lists. All fetches go through
mcp/common/nse_fetch.py (session-cookie warm-up, >=2s/host throttling,
retry-once, circuit breaker) per CLAUDE.md's "be polite to data sources"
rule — never call nseindia.com directly from a tool here.

Endpoint coverage verified live 2026-07-08 (see ROADMAP.md Phase 1 step 3):
- announcements, shareholding pattern, FII/DII flows, ASM list, GSM list —
  all return real JSON.
- bulk/block deals (NSE's /api/historical/bulk-deals and /block-deals) are
  DOWN — 503 "maintenance downtime" regardless of params, retried across
  multiple param variations and fresh cookie sessions. This looks like a
  genuine outage or deprecation on NSE's side, not a request-shape bug.
  get_bulk_block_deals is still registered (NSE may restore it) but returns
  an honest error in `data`, not a silent empty list — don't treat an empty
  result from it as "no deals," treat it as "source unavailable."

Every tool returns {"source", "as_of", "data"} so outputs are
provenance-ready (CLAUDE.md Non-Negotiable Product Rules). No money math
happens here — this is filings/ownership/flow data, not computed figures.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import nse_fetch  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("india_filings")

IST = ZoneInfo("Asia/Kolkata")

REFERERS = {
    "announcements": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    "shareholding": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
    "fii_dii": "https://www.nseindia.com/reports/fii-dii",
    "surveillance": "https://www.nseindia.com/reports/surveillance-actions",
    "bulk_block": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
}


def _envelope(data: Any, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def _safe_fetch(source_label: str, path: str, params: dict[str, Any], referer: str) -> dict[str, Any]:
    """Shared try/wrap: real errors (circuit open, fetch failure) become an honest error envelope, not a crash."""
    try:
        data = nse_fetch.nse_get(path, params=params, referer=referer)
        return _envelope(data, source_label)
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a data gap, see module docstring
        return _envelope({"error": str(exc)}, source_label)


def get_announcements(symbol: str, from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    """Corporate announcements (disclosures, results, corporate actions) for one NSE-listed company.

    symbol: NSE trading symbol, e.g. "RELIANCE". from_date/to_date:
    "DD-MM-YYYY" (NSE's native format, not ISO) — pass both for any bounded
    check. Omitting them does NOT give a recent window: NSE's default
    returns a large, arbitrarily-old fixed slice of history (verified
    live: 714 records spanning 2020-2022, ~500KB, for a stock with no
    unusual filing volume) — always set them explicitly unless you
    specifically want the full unbounded history. Each item includes
    an_dt (announcement time), desc, attchmntFile (PDF URL) — read the PDF
    only if the user needs the filing detail, not for routine digest
    scanning.
    """
    params: dict[str, Any] = {"index": "equities", "symbol": symbol.strip().upper()}
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    return _safe_fetch("NSE corporate-announcements", "/api/corporate-announcements", params, REFERERS["announcements"])


def get_shareholding_pattern(symbol: str) -> dict[str, Any]:
    """Shareholding pattern filings (promoter/public split, submission history) for one NSE-listed company.

    symbol: NSE trading symbol, e.g. "RELIANCE". Returns filing records with
    pr_and_prgrp (promoter+group %), public_val (public %), submissionDate.
    This is the ownership-disclosure filing, not the instruments-master
    sector field (mcp/common/instruments.py) — different data, don't conflate.
    """
    params = {"index": "equities", "symbol": symbol.strip().upper()}
    return _safe_fetch(
        "NSE corporate-share-holdings-master", "/api/corporate-share-holdings-master", params, REFERERS["shareholding"]
    )


def get_fii_dii_flows() -> dict[str, Any]:
    """Latest FII/DII (foreign/domestic institutional investor) buy-sell-net flows, market-wide.

    No symbol argument — this is an aggregate daily market figure (crores),
    not per-stock. Returns one record per category (FII/FPI, DII) for the
    most recent trading day NSE has published.
    """
    return _safe_fetch("NSE fiidiiTradeReact", "/api/fiidiiTradeReact", {}, REFERERS["fii_dii"])


def get_surveillance_list(list_type: str = "ASM") -> dict[str, Any]:
    """Current ASM or GSM surveillance list (stocks under exchange-imposed trading restrictions).

    list_type: "ASM" (Additional Surveillance Measure) or "GSM" (Graded
    Surveillance Measure) — case-insensitive. Useful for red-flag screening
    before recommending/discussing a position: a symbol on either list
    carries added regulatory/liquidity risk the user should know about.
    """
    kind = list_type.strip().upper()
    if kind not in ("ASM", "GSM"):
        return _envelope({"error": f"list_type must be ASM or GSM, got '{list_type}'"}, "NSE surveillance")
    path = "/api/reportASM" if kind == "ASM" else "/api/reportGSM"
    return _safe_fetch(f"NSE report{kind}", path, {"json": "true"}, REFERERS["surveillance"])


def get_bulk_block_deals(symbol: str | None = None) -> dict[str, Any]:
    """Bulk/block deal disclosures (large single-trade transactions) for one symbol or market-wide.

    KNOWN DOWN as of 2026-07-08 (see module docstring) — NSE's endpoint
    returns 503 regardless of params. Still registered so this works
    automatically if NSE restores it; until then expect `data.error` to be
    set. Don't retry this in a loop if it fails — surface "bulk/block deal
    data currently unavailable from NSE" to the user rather than silently
    omitting the section.
    """
    params: dict[str, Any] = {}
    if symbol:
        params["symbol"] = symbol.strip().upper()
    return _safe_fetch("NSE historical/bulk-deals", "/api/historical/bulk-deals", params, REFERERS["bulk_block"])


mcp.tool()(get_announcements)
mcp.tool()(get_shareholding_pattern)
mcp.tool()(get_fii_dii_flows)
mcp.tool()(get_surveillance_list)
mcp.tool()(get_bulk_block_deals)


if __name__ == "__main__":
    mcp.run()
