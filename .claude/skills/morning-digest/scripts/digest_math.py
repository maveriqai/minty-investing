"""Deterministic morning-digest calculations.

Reads a raw kite.get_holdings snapshot and computes overall + day-level P&L,
concentration, and today's movers in code — never in LLM prose, per
CLAUDE.md's Non-Negotiable Product Rules.

Price freshness (fixed 2026-07-08): quantity/average_price come from the
Kite snapshot — they only change when you trade, so a stale snapshot is fine
for those. But last_price/close_price/day_change_percentage in that same
snapshot are frozen at whatever moment Kite was last reachable, which for
headless jobs/ runs can be hours old (Kite OAuth can't complete in
non-interactive mode — see jobs/README.md's "Known limitation"). Verified
2026-07-08: a stale snapshot reported a real held stock as up on the day
when it had actually closed down double digits. Fixed by taking
last_price/previous_close/
day_change_pct from a same-run india_price.get_quote call instead — that
needs no Kite session — and falling back to the Kite snapshot's own fields
only for symbols get_quote can't resolve (G-Secs, some ETFs; yfinance is
equity-focused).

Usage: uv run python digest_math.py data/holdings_2026-07-08.json [data/live_quotes_2026-07-08.json]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def _unwrap_envelope(payload: object) -> object:
    """Unwrap a {"source","as_of","data"} envelope if present; already-bare data passes through unchanged."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _quote_lookup(quotes: list[dict]) -> dict[str, dict]:
    """Map bare tradingsymbol (e.g. "STOCKA") -> quote dict, skipping errors."""
    lookup = {}
    for q in quotes:
        if q.get("error") or q.get("last_price") is None or q.get("previous_close") is None:
            continue
        bare = q["symbol"].removesuffix(".NS").removesuffix(".BO")
        lookup[bare] = q
    return lookup


def compute(holdings: list[dict], quotes: list[dict] | None = None) -> dict:
    quote_by_symbol = _quote_lookup(quotes) if quotes else {}
    rows = []
    for h in holdings:
        qty = h["quantity"]
        avg = h["average_price"]
        symbol = h["tradingsymbol"]
        quote = quote_by_symbol.get(symbol)
        if quote:
            last = quote["last_price"]
            close = quote["previous_close"]
            price_source = "india_price"
        else:
            last = h["last_price"]
            close = h["close_price"]
            price_source = "kite_snapshot"
        invested = qty * avg
        value = qty * last
        prev_value = qty * close
        pnl = value - invested
        pnl_pct = (pnl / invested * 100) if invested else None
        day_pnl = value - prev_value
        day_pnl_pct = (day_pnl / prev_value * 100) if prev_value else None
        rows.append(
            {
                "symbol": symbol,
                "exchange": h["exchange"],
                "quantity": qty,
                "avg_price": round(avg, 2),
                "last_price": round(last, 2),
                "close_price": round(close, 2),
                "invested": round(invested, 2),
                "value": round(value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "day_pnl": round(day_pnl, 2),
                "day_pnl_pct": round(day_pnl_pct, 2) if day_pnl_pct is not None else None,
                "price_source": price_source,
            }
        )

    total_invested = sum(r["invested"] for r in rows)
    total_value = sum(r["value"] for r in rows)
    total_prev_value = total_value - sum(r["day_pnl"] for r in rows)
    total_pnl = total_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else None
    total_day_pnl = sum(r["day_pnl"] for r in rows)
    total_day_pnl_pct = (total_day_pnl / total_prev_value * 100) if total_prev_value else None

    for r in rows:
        r["weight_pct"] = round(r["value"] / total_value * 100, 2) if total_value else None

    by_value = sorted(rows, key=lambda r: r["value"], reverse=True)
    by_day_pct = [r for r in rows if r["day_pnl_pct"] is not None]
    day_gainers = sorted(by_day_pct, key=lambda r: r["day_pnl_pct"], reverse=True)[:5]
    day_losers = sorted(by_day_pct, key=lambda r: r["day_pnl_pct"])[:5]
    by_day_impact = sorted(rows, key=lambda r: r["day_pnl"], reverse=True)
    top_day_contributors = by_day_impact[:5]
    top_day_detractors = list(reversed(by_day_impact[-5:]))

    stale_fallback_symbols = [r["symbol"] for r in rows if r["price_source"] == "kite_snapshot"]

    return {
        "position_count": len(rows),
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2) if total_pnl_pct is not None else None,
        "total_day_pnl": round(total_day_pnl, 2),
        "total_day_pnl_pct": round(total_day_pnl_pct, 2) if total_day_pnl_pct is not None else None,
        "top_concentration": by_value[:10],
        "day_gainers_by_pct": day_gainers,
        "day_losers_by_pct": day_losers,
        "top_day_contributors": top_day_contributors,
        "top_day_detractors": top_day_detractors,
        "stale_fallback_symbols": stale_fallback_symbols,
        "all_positions": rows,
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    holdings = _unwrap_envelope(json.loads(src.read_text()))
    quotes = None
    if len(sys.argv) > 2:
        quotes_path = Path(sys.argv[2])
        quotes = _unwrap_envelope(json.loads(quotes_path.read_text()))
    result = compute(holdings, quotes)
    result["source"] = (
        "kite.get_holdings (quantity/avg_price) + india_price.get_quote (live price)"
        if quotes
        else "kite.get_holdings"
    )
    result["as_of"] = datetime.now(_IST).strftime("%Y-%m-%d")
    result["input_file"] = src.name

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    # Use the quotes file's date, not the holdings file's — the holdings
    # snapshot can be a stale fallback (see jobs/README.md's known
    # limitation) while quotes are always fetched fresh for today's run.
    date_tag = quotes_path.stem.replace("live_quotes_", "") if quotes else src.stem.replace("holdings_", "")
    out_path = out_dir / f"digest_{date_tag}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(
        f"positions={result['position_count']} value=₹{result['total_value']:,.0f} "
        f"day_pnl=₹{result['total_day_pnl']:,.0f} ({result['total_day_pnl_pct']}%) "
        f"total_pnl=₹{result['total_pnl']:,.0f} ({result['total_pnl_pct']}%)"
    )
