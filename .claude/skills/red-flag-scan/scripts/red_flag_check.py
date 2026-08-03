"""Deterministic red-flag checklist for one NSE-listed stock.

Combines five already-fetched tool envelopes (shareholding pattern,
ASM/GSM surveillance lists, announcements, news, fundamentals) into a fixed
set of checks — never an LLM judgment call, per CLAUDE.md's "deterministic
calculation only" rule. Every input is optional: a missing/failed upstream
call skips its checks and is reported under `checks_skipped`, not silently
ignored or guessed around (the same honest-gap policy as the rest of Minty).

Keyword scanning (announcements/news) flags a *mention*, not a verdict — the
skill composing the brief should quote the matched text and let the user
judge severity, not assert wrongdoing.

Usage:
  uv run python red_flag_check.py --symbol STOCKA \\
    --shareholding data/shareholding_STOCKA_2026-07-08.json \\
    --surveillance-asm data/surveillance_asm_2026-07-08.json \\
    --surveillance-gsm data/surveillance_gsm_2026-07-08.json \\
    --announcements data/announcements_STOCKA_2026-07-08.json \\
    --news data/news_STOCKA_2026-07-08.json \\
    --fundamentals data/fundamentals_STOCKA_2026-07-08.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

RED_FLAG_KEYWORDS = [
    "auditor resignation",
    "resignation of auditor",
    "resignation of statutory auditor",
    "related party",
    "litigation",
    "default",
    "delay in results",
    "postponement of results",
    "rating downgrade",
    "credit rating downgrade",
    "sebi action",
    "sebi order",
    "investigation",
    "fraud",
    "insolvency",
    "winding up",
    "corporate insolvency resolution",
]

# yfinance's debt_to_equity is a percentage, not a raw ratio (verified 2026-07-08:
# RELIANCE reads 36.653 — a raw 36.65x ratio would be implausible for one of India's
# most well-capitalized companies; 36.65% i.e. a ~0.37 D/E ratio matches its known
# real profile). Threshold below is in the same percentage units.
DEBT_TO_EQUITY_THRESHOLD = 200.0  # i.e. D/E ratio > 2.0x
CURRENT_RATIO_THRESHOLD = 1.0


def _envelope_data(payload: dict[str, Any] | None) -> Any:
    """Unwrap a {"source","as_of","data"} envelope; None passes through."""
    if payload is None:
        return None
    data = payload.get("data")
    if isinstance(data, dict) and "error" in data:
        return None  # upstream tool failed — treat as missing, not as an empty result
    return data


def _check_promoter_holding(shareholding: dict | None) -> tuple[list[dict], bool]:
    data = _envelope_data(shareholding)
    if not data:
        return [], False
    records = []
    for rec in data:
        try:
            parsed_date = datetime.strptime(rec["date"], "%d-%b-%Y")
            pct = float(rec["pr_and_prgrp"])
        except (KeyError, ValueError, TypeError):
            continue
        records.append((parsed_date, pct, rec["date"]))
    if len(records) < 2:
        return [], True
    records.sort(key=lambda r: r[0])
    (_, prev_pct, prev_label), (_, latest_pct, latest_label) = records[-2], records[-1]
    drop = prev_pct - latest_pct
    if drop > 0.5:
        return [
            {
                "category": "promoter_holding_decrease",
                "severity": "high",
                "evidence": f"Promoter+group holding fell from {prev_pct}% ({prev_label}) to {latest_pct}% ({latest_label})",
            }
        ], True
    return [], True


def _check_surveillance(surveillance: dict | None, symbol: str, list_type: str) -> tuple[list[dict], bool]:
    """ASM comes back as {"longterm": {"data": [...]}, "shortterm": {"data": [...]}}; GSM as a flat list — both verified live 2026-07-08, not a guess."""
    data = _envelope_data(surveillance)
    if not data:
        return [], False
    if isinstance(data, list):
        buckets = {"": data}
    else:
        buckets = {b: (data.get(b) or {}).get("data") or [] for b in ("longterm", "shortterm")}
    flags = []
    for bucket, entries in buckets.items():
        for entry in entries:
            if entry.get("symbol", "").strip().upper() == symbol:
                label = f" ({bucket})" if bucket else ""
                flags.append(
                    {
                        "category": f"{list_type.lower()}_surveillance",
                        "severity": "high",
                        "evidence": entry.get("survDesc") or f"On {list_type} surveillance list{label}",
                    }
                )
    return flags, True


def _check_keywords(items: list[dict], text_fields: list[str], category: str) -> list[dict]:
    flags = []
    for item in items:
        haystack = " ".join(str(item.get(f, "")) for f in text_fields).lower()
        for kw in RED_FLAG_KEYWORDS:
            if kw in haystack:
                flags.append(
                    {
                        "category": category,
                        "severity": "medium",
                        "evidence": f"Matched '{kw}': {item.get(text_fields[0], '')[:200]}",
                    }
                )
    return flags


def _check_announcements(announcements: dict | None) -> tuple[list[dict], bool]:
    data = _envelope_data(announcements)
    if data is None:
        return [], False
    return _check_keywords(data, ["desc", "attchmntText"], "announcement_keyword"), True


def _check_news(news: dict | None) -> tuple[list[dict], bool]:
    data = _envelope_data(news)
    if data is None:
        return [], False
    return _check_keywords(data, ["title"], "news_keyword"), True


def _check_fundamentals(fundamentals: dict | None) -> tuple[list[dict], bool]:
    data = _envelope_data(fundamentals)
    if not data:
        return [], False
    flags = []
    dte = data.get("debt_to_equity")
    if dte is not None and dte > DEBT_TO_EQUITY_THRESHOLD:
        flags.append(
            {
                "category": "high_leverage",
                "severity": "medium",
                "evidence": f"Debt/Equity = {dte}% (heuristic threshold: >{DEBT_TO_EQUITY_THRESHOLD}%)",
            }
        )
    cr = data.get("current_ratio")
    if cr is not None and cr < CURRENT_RATIO_THRESHOLD:
        flags.append(
            {
                "category": "liquidity_stress",
                "severity": "medium",
                "evidence": f"Current ratio = {cr} (heuristic threshold: <{CURRENT_RATIO_THRESHOLD})",
            }
        )
    return flags, True


def compute(
    symbol: str,
    shareholding: dict | None = None,
    surveillance_asm: dict | None = None,
    surveillance_gsm: dict | None = None,
    announcements: dict | None = None,
    news: dict | None = None,
    fundamentals: dict | None = None,
) -> dict:
    symbol = symbol.strip().upper()
    flags: list[dict] = []
    checks_performed: list[str] = []
    checks_skipped: list[str] = []

    for name, (check_flags, ran) in {
        "promoter_holding": _check_promoter_holding(shareholding),
        "asm_surveillance": _check_surveillance(surveillance_asm, symbol, "ASM"),
        "gsm_surveillance": _check_surveillance(surveillance_gsm, symbol, "GSM"),
        "announcement_keywords": _check_announcements(announcements),
        "news_keywords": _check_news(news),
        "fundamentals_thresholds": _check_fundamentals(fundamentals),
    }.items():
        flags.extend(check_flags)
        (checks_performed if ran else checks_skipped).append(name)

    return {
        "symbol": symbol,
        "flags": flags,
        "flag_count": len(flags),
        "checks_performed": checks_performed,
        "checks_skipped": checks_skipped,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--shareholding")
    parser.add_argument("--surveillance-asm")
    parser.add_argument("--surveillance-gsm")
    parser.add_argument("--announcements")
    parser.add_argument("--news")
    parser.add_argument("--fundamentals")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    def _load(path: str | None) -> dict | None:
        return json.loads(Path(path).read_text()) if path else None

    result = compute(
        symbol=args.symbol,
        shareholding=_load(args.shareholding),
        surveillance_asm=_load(args.surveillance_asm),
        surveillance_gsm=_load(args.surveillance_gsm),
        announcements=_load(args.announcements),
        news=_load(args.news),
        fundamentals=_load(args.fundamentals),
    )
    result["as_of"] = args.as_of
    result["source"] = "red_flag_check.py over india_filings/india_news/india_price tool outputs"

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"red_flags_{result['symbol']}_{args.as_of}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(result, indent=2))
