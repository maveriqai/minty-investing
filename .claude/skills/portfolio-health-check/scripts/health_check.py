"""Deterministic portfolio health-check calculations.

Reads a raw kite.get_holdings snapshot and computes concentration, P&L, and
winner/loser rankings in code — never in LLM prose, per CLAUDE.md's
Non-Negotiable Product Rules. Writes results/health_check_<date>.json,
relative to the current working directory (run this from inside the
workspace, not the skill directory).

Usage: uv run python health_check.py data/holdings_2026-07-08.json
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


def compute(holdings: list[dict]) -> dict:
    rows = []
    for h in holdings:
        qty = h["quantity"]
        avg = h["average_price"]
        last = h["last_price"]
        invested = qty * avg
        value = qty * last
        pnl = value - invested
        pnl_pct = (pnl / invested * 100) if invested else None
        rows.append(
            {
                "symbol": h["tradingsymbol"],
                "exchange": h["exchange"],
                "quantity": qty,
                "avg_price": round(avg, 2),
                "last_price": round(last, 2),
                "invested": round(invested, 2),
                "value": round(value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            }
        )

    total_invested = sum(r["invested"] for r in rows)
    total_value = sum(r["value"] for r in rows)
    total_pnl = total_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else None

    for r in rows:
        r["weight_pct"] = round(r["value"] / total_value * 100, 2) if total_value else None

    by_value = sorted(rows, key=lambda r: r["value"], reverse=True)
    by_pnl_pct = [r for r in rows if r["pnl_pct"] is not None]
    winners = sorted(by_pnl_pct, key=lambda r: r["pnl_pct"], reverse=True)[:10]
    losers = sorted(by_pnl_pct, key=lambda r: r["pnl_pct"])[:10]
    top_concentration = by_value[:10]

    return {
        "position_count": len(rows),
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2) if total_pnl_pct is not None else None,
        "top_concentration": top_concentration,
        "top_winners_by_pnl_pct": winners,
        "top_losers_by_pnl_pct": losers,
        "all_positions": rows,
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    holdings = _unwrap_envelope(json.loads(src.read_text()))
    result = compute(holdings)
    result["source"] = "kite.get_holdings"
    result["as_of"] = datetime.now(_IST).strftime("%Y-%m-%d")
    result["input_file"] = src.name

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    date_tag = src.stem.replace("holdings_", "")
    out_path = out_dir / f"health_check_{date_tag}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(f"positions={result['position_count']} value=₹{result['total_value']:,.0f} "
          f"pnl=₹{result['total_pnl']:,.0f} ({result['total_pnl_pct']}%)")
