"""Deterministic valuation/quality ranking over a candidate universe.

Reads a candidate list (list_candidates.py's own output) and, for each
candidate, looks up that symbol's already-captured
data/fundamentals_<SYMBOL>_<as-of>.json (india_price, yfinance-backed) and
data/fundamentals_screener_<SYMBOL>_<as-of>.json (india_screener,
Screener.in-backed, optional) — engine/tool_capture.py auto-saves both
tools' calls under exactly these filenames the moment each is made, so
there's no manual "assemble a batch file" step for the model to get right
(the failure mode engine/skill_tools.py's own docstring documents finding
live for hand-typed Bash). A candidate with no matching india_price file
(never fetched) is excluded with a reason, same as one whose fetch came
back with an error. Quotes are still passed as a single file
(india_price.get_quote takes a symbol list, so one batched call already
captures all candidates together). Ranks in code, never by LLM judgment,
per docs/vision.md §5's "deterministic calculation only" rule. Writes
results/screen_<industry-slug>_<date>.json relative to the current working
directory (the active workspace — set by the run_screen_rank tool).

ROE sourcing (fixes #9 — see docs/screener-integration-design.md §1):
yfinance's return_on_equity_pct comes back null for entire sectors
(confirmed live: Consumer Cyclical, Energy), which used to zero out this
skill's entire ranked list for those sectors. When a candidate's
india_screener fundamentals are available and not an error, its roe_pct is
preferred for ranking; yfinance's return_on_equity_pct is the fallback when
Screener data wasn't fetched or came back empty. Both raw figures are kept
in the output alongside which one was actually used (`roe_source`) — never
silently substituted, since docs/screener-integration-design.md §2
established these are genuinely different numbers by methodology, not
interchangeable.

Ranking: candidates missing trailing_pe (india_price only — Screener's
trailing_pe isn't consulted here, this fix is scoped to the documented ROE
gap) or with no ROE available from either source are excluded from ranking
(not silently dropped — reported under `excluded` with a reason) since
there's nothing to rank them on. Remaining candidates get a
composite_rank_score = ascending-PE rank + descending-ROE rank (ties broken
by symbol) — lower is better. This is a simple, transparent heuristic, not
a valuation model; it surfaces candidates worth a closer look, not a buy
list.

Usage:
  uv run python screen_rank.py --industry "Automobile and Auto Components" \\
    --candidates data/candidates_automobile-and-auto-components_2026-08-20.json \\
    [--quotes data/live_quotes_2026-08-20.json]
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# yfinance's debt_to_equity is a percentage, not a raw ratio — see
# .claude/skills/red-flag-scan/scripts/red_flag_check.py for the
# RELIANCE-based verification.
DEBT_TO_EQUITY_FLAG_THRESHOLD = 200.0  # i.e. D/E ratio > 2.0x


def _bare(symbol: str) -> str:
    return symbol.removesuffix(".NS").removesuffix(".BO")


def _slug(industry: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", industry.lower()).strip("-")


def compute(
    candidates: list[dict],
    fundamentals_by_symbol: dict[str, dict],
    quotes: list[dict] | None = None,
    screener_fundamentals_by_symbol: dict[str, dict] | None = None,
) -> dict:
    quote_by_symbol = {_bare(q["symbol"]): q for q in (quotes or []) if not q.get("error")}
    screener_fundamentals_by_symbol = screener_fundamentals_by_symbol or {}

    rankable: list[dict] = []
    excluded: list[dict] = []

    for c in candidates:
        symbol = c["symbol"]
        f = fundamentals_by_symbol.get(symbol)
        if f is None:
            excluded.append({"symbol": symbol, "reason": "no fundamentals data fetched for this candidate"})
            continue
        if f.get("error"):
            excluded.append({"symbol": symbol, "reason": f"fundamentals error: {f['error']}"})
            continue

        screener_f = screener_fundamentals_by_symbol.get(symbol)
        screener_roe = screener_f.get("roe_pct") if screener_f and not screener_f.get("error") else None
        yfinance_roe = f.get("return_on_equity_pct")
        # Prefer Screener's ROE — fixes #9's sector-wide yfinance nulls — but
        # never conflate the two: both raw figures ride along in the output.
        if screener_roe is not None:
            roe, roe_source = screener_roe, "screener.in"
        elif yfinance_roe is not None:
            roe, roe_source = yfinance_roe, "yfinance"
        else:
            roe, roe_source = None, None

        pe = f.get("trailing_pe")
        if pe is None or pe <= 0 or roe is None:
            excluded.append(
                {
                    "symbol": symbol,
                    "reason": "missing or non-positive trailing_pe, or ROE unavailable from both "
                    "india_price and india_screener",
                }
            )
            continue
        quote = quote_by_symbol.get(symbol)
        rankable.append(
            {
                "symbol": symbol,
                "name": c.get("name"),
                "trailing_pe": pe,
                "return_on_equity_pct": yfinance_roe,
                "screener_roe_pct": screener_roe,
                "roe_pct_used": roe,
                "roe_source": roe_source,
                "debt_to_equity": f.get("debt_to_equity"),
                "market_cap_inr": f.get("market_cap_inr"),
                "last_price": quote.get("last_price") if quote else None,
                "day_change_pct": quote.get("day_change_pct") if quote else None,
                "high_leverage_flag": f.get("debt_to_equity") is not None
                and f["debt_to_equity"] > DEBT_TO_EQUITY_FLAG_THRESHOLD,
            }
        )

    pe_order = sorted(rankable, key=lambda r: (r["trailing_pe"], r["symbol"]))
    pe_rank = {r["symbol"]: i for i, r in enumerate(pe_order)}
    roe_order = sorted(rankable, key=lambda r: (-r["roe_pct_used"], r["symbol"]))
    roe_rank = {r["symbol"]: i for i, r in enumerate(roe_order)}

    for r in rankable:
        r["composite_rank_score"] = pe_rank[r["symbol"]] + roe_rank[r["symbol"]]

    rankable.sort(key=lambda r: (r["composite_rank_score"], r["symbol"]))

    return {
        "candidate_count": len(candidates),
        "ranked_count": len(rankable),
        "excluded_count": len(excluded),
        "ranked": rankable,
        "excluded": excluded,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--industry", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--quotes")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    candidates_payload = json.loads(Path(args.candidates).read_text())
    candidates = candidates_payload["candidates"]

    fundamentals_by_symbol: dict[str, dict] = {}
    data_dir = Path.cwd() / "data"
    for c in candidates:
        symbol = c["symbol"]
        fpath = data_dir / f"fundamentals_{symbol}_{args.as_of}.json"
        if fpath.is_file():
            payload = json.loads(fpath.read_text())
            fundamentals_by_symbol[symbol] = payload.get("data", payload)

    # Optional — engine/tool_capture.py only writes this file if the model
    # actually called india_screener.get_fundamentals for that symbol.
    # Missing is not an error, it just falls back to yfinance's ROE alone
    # for that candidate (the pre-fix #9 behavior).
    screener_fundamentals_by_symbol: dict[str, dict] = {}
    for c in candidates:
        symbol = c["symbol"]
        fpath = data_dir / f"fundamentals_screener_{symbol}_{args.as_of}.json"
        if fpath.is_file():
            payload = json.loads(fpath.read_text())
            screener_fundamentals_by_symbol[symbol] = payload.get("data", payload)

    quotes = json.loads(Path(args.quotes).read_text()).get("data") if args.quotes else None

    result = compute(candidates, fundamentals_by_symbol, quotes, screener_fundamentals_by_symbol)
    result["industry"] = args.industry
    result["as_of"] = args.as_of
    result["source"] = (
        "screen_rank.py over india_price.get_fundamentals"
        + (" + india_screener.get_fundamentals" if screener_fundamentals_by_symbol else "")
        + (" + india_price.get_quote" if quotes else "")
        + " (candidate universe: local instruments master, Nifty 500 coverage only)"
    )

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"screen_{_slug(args.industry)}_{args.as_of}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(result, indent=2))
