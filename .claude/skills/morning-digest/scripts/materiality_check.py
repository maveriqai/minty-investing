"""Deterministic sector-aware materiality scoring for morning-digest.

Reads today's bounded symbol set (top_concentration ∪ day_gainers_by_pct ∪
day_losers_by_pct from digest_math.py's own output — same set now covers
both news and announcements, replacing the old top-10-by-value-only bound
for announcements) plus each symbol's already-fetched news/announcement
envelopes, and scores them via mcp/common/sector_materiality.py's rubric —
never an LLM judgment call, per CLAUDE.md's "deterministic calculation
only" rule. Every input is optional per-symbol: a missing news or
announcement file for a symbol skips that source and is reported under
symbols_no_news_data/symbols_no_announcement_data, not silently ignored or
guessed around (the same honest-gap policy as red_flag_check.py and
surveillance_check.py).

Same-symbol news and announcement flags that match the same signal (e.g. a
results filing reported by both a news wire and the exchange announcement
itself) are collapsed to one — left as an open question in the original
plan pending a real dry run, then confirmed a real problem: a 2026-07-24
live run had CIPLA's Q1 results consume 2 of an 8-flag display cap via
near-duplicate news+announcement flags, crowding out distinct events from
other symbols. See _dedupe_same_signal().

Usage:
  uv run python materiality_check.py results/digest_2026-07-21.json 2026-07-21
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _find_repo_root(start: Path) -> Path:
    """Walk up from this file to the directory containing mcp/common.

    A fixed parents[N] index breaks here: this canonical script also ships
    as a generated view under .claude/skills/ (one directory deeper than
    skills/), and a fixed-depth index silently resolves to the wrong
    directory in that copy instead of erroring — verified 2026-07-23
    (ModuleNotFoundError from .claude/skills/'s copy). Searching for the
    mcp/common marker works from either location.
    """
    for candidate in (start, *start.parents):
        if (candidate / "mcp" / "common").is_dir():
            return candidate
    raise RuntimeError(f"could not locate repo root (no mcp/common found) starting from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(REPO_ROOT / "mcp" / "common"))
import sector_materiality  # noqa: E402

SectorResolver = Callable[[str], tuple[str | None, str]]


def _bounded_symbols(digest: dict[str, Any]) -> dict[str, float | None]:
    """symbol -> weight_pct, from top_concentration ∪ day_gainers_by_pct ∪ day_losers_by_pct."""
    weights: dict[str, float | None] = {}
    for key in ("top_concentration", "day_gainers_by_pct", "day_losers_by_pct"):
        for row in digest.get(key) or []:
            weights.setdefault(row["symbol"], row.get("weight_pct"))
    return weights


def _envelope_items(payload: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Unwrap a {"source","as_of","data"} envelope; error/missing/non-list -> None."""
    if payload is None:
        return None
    data = payload.get("data")
    if isinstance(data, dict) and "error" in data:
        return None  # upstream tool failed — treat as missing, not as an empty result
    if not isinstance(data, list):
        return None
    return data


def _dedupe_same_signal(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse same-symbol flags matching the same signal to the single most informative one.

    News and announcement flags for the same underlying event (e.g. a
    results filing covered both as a news story and as the exchange
    announcement itself) share {symbol, matched_signal} and add little
    beyond restating each other. Keep whichever headline is longer — a
    crude but effective proxy for "carries more distinct fact content",
    matching the real 2026-07-24 case where CIPLA's news headline ("Q1 net
    profit fell 39% YoY to Rs789 Cr...") carried figures its announcement
    duplicate ("Outcome of Board Meeting") didn't. Flags for the same
    symbol matching *different* signals (e.g. INDUSINDBK's results
    headline vs. its separate asset-quality headline) are never collapsed
    — only exact {symbol, matched_signal} collisions are.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for f in flags:
        key = (f["symbol"], f["matched_signal"])
        current = best.get(key)
        if current is None or len(f["headline"]) > len(current["headline"]):
            best[key] = f
    return list(best.values())


def compute(
    digest: dict[str, Any],
    news_payloads: dict[str, dict[str, Any] | None],
    announcement_payloads: dict[str, dict[str, Any] | None],
    sector_resolver: SectorResolver | None = None,
) -> dict[str, Any]:
    sector_resolver = sector_resolver or sector_materiality.sector_for
    weights = _bounded_symbols(digest)

    flags: list[dict[str, Any]] = []
    symbols_no_news_data: list[str] = []
    symbols_no_announcement_data: list[str] = []

    for symbol, weight_pct in weights.items():
        canonical_sector, sector_source = sector_resolver(symbol)

        news_items = _envelope_items(news_payloads.get(symbol))
        if news_items is None:
            symbols_no_news_data.append(symbol)
            news_items = []
        for f in sector_materiality.score_items(symbol, canonical_sector, news_items, ["title"], ref_fields=["link"]):
            flags.append(
                {
                    "symbol": symbol,
                    "sector": canonical_sector,
                    "sector_source": sector_source,
                    "source_type": "news",
                    "headline": f["evidence"],
                    "link": f.get("link"),
                    "matched_signal": f["signal"],
                    "severity": f["severity"],
                    "rationale": f["rationale"],
                    "portfolio_weight_pct": weight_pct,
                }
            )

        ann_items = _envelope_items(announcement_payloads.get(symbol))
        if ann_items is None:
            symbols_no_announcement_data.append(symbol)
            ann_items = []
        for f in sector_materiality.score_items(
            symbol, canonical_sector, ann_items, ["desc", "attchmntText"], ref_fields=["attchmntFile"]
        ):
            flags.append(
                {
                    "symbol": symbol,
                    "sector": canonical_sector,
                    "sector_source": sector_source,
                    "source_type": "announcement",
                    "headline": f["evidence"],
                    "link": f.get("attchmntFile"),
                    "matched_signal": f["signal"],
                    "severity": f["severity"],
                    "rationale": f["rationale"],
                    "portfolio_weight_pct": weight_pct,
                }
            )

    raw_flag_count = len(flags)
    flags = _dedupe_same_signal(flags)

    severity_rank = {"high": 0, "medium": 1}
    flags.sort(key=lambda fl: (severity_rank.get(fl["severity"], 2), -(fl["portfolio_weight_pct"] or 0)))

    return {
        "flag_count": len(flags),
        "duplicate_flags_collapsed": raw_flag_count - len(flags),
        "flags": flags,
        "symbols_checked": sorted(weights),
        "symbols_no_news_data": symbols_no_news_data,
        "symbols_no_announcement_data": symbols_no_announcement_data,
    }


if __name__ == "__main__":
    digest_path = Path(sys.argv[1])
    date_tag = sys.argv[2]

    digest = json.loads(digest_path.read_text())
    weights = _bounded_symbols(digest)

    data_dir = Path.cwd() / "data"
    news_payloads: dict[str, dict[str, Any] | None] = {}
    announcement_payloads: dict[str, dict[str, Any] | None] = {}
    for symbol in weights:
        news_path = data_dir / f"news_{symbol}_{date_tag}.json"
        ann_path = data_dir / f"announcements_{symbol}_{date_tag}.json"
        news_payloads[symbol] = json.loads(news_path.read_text()) if news_path.exists() else None
        announcement_payloads[symbol] = json.loads(ann_path.read_text()) if ann_path.exists() else None

    result = compute(digest, news_payloads, announcement_payloads)
    result["source"] = "materiality_check.py over india_news/india_filings.get_announcements + mcp/common/sector_materiality"
    result["as_of"] = datetime.now().strftime("%Y-%m-%d")
    result["input_files"] = [digest_path.name]

    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"materiality_flags_{date_tag}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(
        f"symbols_checked={len(result['symbols_checked'])} flags={result['flag_count']} "
        f"(collapsed {result['duplicate_flags_collapsed']} duplicate) "
        f"no_news={len(result['symbols_no_news_data'])} no_announcements={len(result['symbols_no_announcement_data'])}"
    )
