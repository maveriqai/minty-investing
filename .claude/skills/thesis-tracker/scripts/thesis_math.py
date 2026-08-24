"""Deterministic entry-to-current price move for a thesis-tracker update.

Computes % move and days elapsed since a thesis's entry price/date, in code
rather than LLM arithmetic — the only numeric claim this skill ever makes.
Writes results/thesis_<symbol>_<date>.json relative to the current working
directory. Invoked through the run_thesis_math SDK tool
(engine/skill_tools.py), which sets that cwd to the active workspace — not
run directly via Bash.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def compute(entry_price: float, entry_date: str, current_price: float, as_of: str) -> dict:
    entry = date.fromisoformat(entry_date)
    today = date.fromisoformat(as_of)
    days_elapsed = (today - entry).days
    move_pct = (current_price - entry_price) / entry_price * 100
    return {
        "entry_price": entry_price,
        "entry_date": entry_date,
        "current_price": current_price,
        "as_of": as_of,
        "days_elapsed": days_elapsed,
        "move_pct": round(move_pct, 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--entry-price", type=float, required=True)
    parser.add_argument("--entry-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--current-price", type=float, required=True)
    parser.add_argument("--as-of", default=datetime.now(_IST).strftime("%Y-%m-%d"), help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    result = compute(args.entry_price, args.entry_date, args.current_price, args.as_of)
    result["symbol"] = args.symbol.strip().upper()
    result["source"] = "thesis_math.py (entry price from kite_gateway.get_holdings or user input; current price from india_price.get_quote)"

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"thesis_{result['symbol']}_{args.as_of}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(result, indent=2))
