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

`get_filing_document` fetches and extracts text from the actual filed
document (a PDF) behind an announcement's `attchmntFile` URL — added for
issue #25, closing the gap that previously drove the model to raw Bash+curl
against nsearchives.nseindia.com directly, bypassing nse_fetch.py's
cache/throttle/circuit-breaker and Minty's own auto-capture/Sources-footer
grounding entirely. Bash is no longer in Minty's builtin tool surface at all
(engine/config.py) — this tool is the governed replacement for reading a
filing's actual content, not just its announcement metadata.

`get_surveillance_list` takes an optional `symbols` filter — added for
issue #24, after the unfiltered market-wide ASM/GSM list (tens of
thousands of characters) exceeded the Claude Agent SDK's own tool-result
size cap live, twice, and got silently captured as a plain-text redirect
in place of real data. Every real caller already knows which symbols it
cares about (morning-digest's held set, red-flag-scan's one candidate), so
both now pass `symbols` and get back only the matching entries.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pypdf

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


def _filter_surveillance_by_symbols(data: Any, wanted: set[str]) -> Any:
    """Recursively walks an NSE ASM/GSM payload, keeping only entries whose
    `symbol` field is in `wanted` — everything else about the shape is
    preserved untouched. ASM and GSM nest their symbol lists differently
    (GSM is a flat list; ASM is `{longterm: {data: [...]}, shortterm:
    {data: [...]}}}` — see `scripts/surveillance_check.py`'s own
    `_extract_symbols` docstring for the same observation), so this makes
    no assumption about a fixed key path: a list whose items are all
    symbol-bearing dicts gets filtered in place, any other list/dict just
    gets recursed into.
    """
    if isinstance(data, dict):
        if isinstance(data.get("symbol"), str):
            return data
        return {key: _filter_surveillance_by_symbols(value, wanted) for key, value in data.items()}
    if isinstance(data, list):
        if data and all(isinstance(item, dict) and isinstance(item.get("symbol"), str) for item in data):
            return [item for item in data if item["symbol"].strip().upper() in wanted]
        return [_filter_surveillance_by_symbols(item, wanted) for item in data]
    return data


def get_surveillance_list(list_type: str = "ASM", symbols: list[str] | None = None) -> dict[str, Any]:
    """Current ASM or GSM surveillance list (stocks under exchange-imposed trading restrictions).

    list_type: "ASM" (Additional Surveillance Measure) or "GSM" (Graded
    Surveillance Measure) — case-insensitive. Useful for red-flag screening
    before recommending/discussing a position: a symbol on either list
    carries added regulatory/liquidity risk the user should know about.

    symbols: the NSE trading symbols you actually care about (e.g. today's
    held symbols, or the one candidate being screened) — when given, only
    matching entries are returned. Pass this whenever you already know
    which symbols you're checking, which is true for every skill that
    calls this today (morning-digest, red-flag-scan) — the unfiltered
    market-wide list runs into tens of thousands of characters and can
    exceed the model's own tool-result size cap, which silently substitutes
    a plain-text "exceeds maximum allowed tokens" redirect in place of the
    real data (issue #24). Omit only when the full market-wide list is
    genuinely what's needed.
    """
    kind = list_type.strip().upper()
    if kind not in ("ASM", "GSM"):
        return _envelope({"error": f"list_type must be ASM or GSM, got '{list_type}'"}, "NSE surveillance")
    path = "/api/reportASM" if kind == "ASM" else "/api/reportGSM"
    result = _safe_fetch(f"NSE report{kind}", path, {"json": "true"}, REFERERS["surveillance"])
    if symbols and isinstance(result.get("data"), (dict, list)):
        wanted = {s.strip().upper() for s in symbols}
        result = {**result, "data": _filter_surveillance_by_symbols(result["data"], wanted)}
    return result


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


# Comfortably above what a results press release/investor presentation needs
# (SBI's Q1FY27 press release, read live during issue #25's own discovery,
# extracted well under this) while staying far under the SDK's stdio buffer
# cap (see engine/config.py's _MAX_BUFFER_SIZE docstring for that history).
_MAX_EXTRACTED_CHARS = 20_000


def _extract_pdf_text(content: bytes) -> tuple[str, int]:
    """Returns (extracted text, page count). Text is truncated to `_MAX_EXTRACTED_CHARS`, per-page,
    so a truncation lands on a page boundary rather than mid-sentence."""
    reader = pypdf.PdfReader(io.BytesIO(content))
    parts: list[str] = []
    total_chars = 0
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if total_chars + len(page_text) > _MAX_EXTRACTED_CHARS:
            parts.append("... [truncated]")
            break
        parts.append(page_text)
        total_chars += len(page_text)
    return "\n".join(parts).strip(), len(reader.pages)


def get_filing_document(url: str) -> dict[str, Any]:
    """Fetch and extract text from the actual filed document (a PDF) behind an announcement.

    `url` must be the exact `attchmntFile` value from a prior `get_announcements` call — an NSE-owned
    host (e.g. nsearchives.nseindia.com); anything else is refused. Use this when a claim needs checking
    against the primary source itself, not just the announcement's own description field. Routes through
    mcp/common/nse_fetch.py's cache/throttle/circuit-breaker like every other call in this module, cached
    for 30 days since a filed document never changes once submitted. Returns extracted text (not raw PDF
    bytes) truncated to roughly 20k characters on a page boundary — read the returned text, don't try to
    reconstruct or re-fetch the document from it. Never fetch a filing document via Bash/curl — that
    bypasses this module's caching/rate-limiting and Minty's own auto-capture/Sources-footer grounding
    entirely (issue #25).
    """
    try:
        content = nse_fetch.nse_get_binary(url, referer=REFERERS["announcements"])
        text, num_pages = _extract_pdf_text(content)
        return _envelope({"url": url, "num_pages": num_pages, "text": text}, "NSE filing document")
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a data gap, see module docstring
        return _envelope({"error": str(exc)}, "NSE filing document")


mcp.tool()(get_announcements)
mcp.tool()(get_shareholding_pattern)
mcp.tool()(get_fii_dii_flows)
mcp.tool()(get_surveillance_list)
mcp.tool()(get_bulk_block_deals)
mcp.tool()(get_filing_document)


if __name__ == "__main__":
    mcp.run()
