"""Deterministic volatility/drawdown stats for a single-position deep dive.

Reads a raw india_price.get_daily_ohlcv bars list (JSON) and computes 1yr
return, max drawdown, annualized daily-return volatility, and the single
worst daily move — in code, not LLM eyeballing of the bar list. Writes
results/<symbol>_volatility_<date>.json relative to the current working
directory (run this from inside the workspace, not the skill directory).

Usage: uv run python volatility.py data/STOCKA_ohlcv_1y.json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path


def compute(bars: list[dict]) -> dict:
    clean = [
        b for b in bars
        if b.get("close") is not None and not math.isnan(b["close"])
    ]
    closes = [b["close"] for b in clean]

    start, end = closes[0], closes[-1]
    total_return_pct = (end - start) / start * 100

    peak = closes[0]
    max_dd_pct = 0.0
    max_dd_dates = (clean[0]["date"], clean[0]["date"])
    peak_date = clean[0]["date"]
    for b in clean:
        c = b["close"]
        if c > peak:
            peak = c
            peak_date = b["date"]
        dd = (c - peak) / peak * 100
        if dd < max_dd_pct:
            max_dd_pct = dd
            max_dd_dates = (peak_date, b["date"])

    daily_rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))
    ]
    mean = sum(daily_rets) / len(daily_rets)
    variance = sum((r - mean) ** 2 for r in daily_rets) / len(daily_rets)
    daily_vol_pct = math.sqrt(variance) * 100
    annualized_vol_pct = daily_vol_pct * math.sqrt(252)

    worst_day = min(clean[1:], key=lambda b: (b["close"] - clean[clean.index(b) - 1]["close"]) / clean[clean.index(b) - 1]["close"])
    worst_idx = clean.index(worst_day)
    worst_day_ret_pct = (clean[worst_idx]["close"] - clean[worst_idx - 1]["close"]) / clean[worst_idx - 1]["close"] * 100

    return {
        "period": f"{clean[0]['date']} to {clean[-1]['date']}",
        "start_close": start,
        "end_close": end,
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_peak_to_trough": max_dd_dates,
        "daily_vol_pct": round(daily_vol_pct, 2),
        "annualized_vol_pct": round(annualized_vol_pct, 2),
        "worst_single_day": {"date": worst_day["date"], "return_pct": round(worst_day_ret_pct, 2)},
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    bars = json.loads(src.read_text())
    result = compute(bars)
    result["source"] = "india_price.get_daily_ohlcv"
    result["as_of"] = datetime.now().strftime("%Y-%m-%d")
    result["input_file"] = src.name

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    symbol_tag = src.stem.replace("_ohlcv_1y", "")
    out_path = out_dir / f"{symbol_tag}_volatility_{result['as_of']}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(result, indent=2))
