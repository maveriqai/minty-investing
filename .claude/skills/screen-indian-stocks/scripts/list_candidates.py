"""Deterministic candidate universe for one industry, from the local instruments master.

A plain local SQLite read (mcp/common/instruments.symbols_by_industry) — no
network call. Invoked through the run_list_candidates SDK tool
(engine/skill_tools.py), same as every other deterministic script in this
repo, rather than run directly via Bash — a typed tool call is more
reliable than a hand-assembled shell command. Coverage is Nifty 500
constituents only (see instruments.py's module docstring) — this is a
starting universe for screening, not the full ~22k NSE/BSE listing.
Writes data/candidates_<industry-slug>_<date>.json (an input for the next
step, screen_rank.py — not a final result, so it goes under data/, not
results/).

Usage: uv run python list_candidates.py "Automobile and Auto Components" --limit 25
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Walk up from this file to the directory containing mcp/common,
    rather than a fixed parents[N] index that would silently break if this
    script's own path depth ever changes."""
    for candidate in (start, *start.parents):
        if (candidate / "mcp" / "common").is_dir():
            return candidate
    raise RuntimeError(f"could not locate repo root (no mcp/common found) starting from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(REPO_ROOT / "mcp" / "common"))
import instruments


def _slug(industry: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", industry.lower()).strip("-")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("industry", help="Exact industry label, e.g. 'Automobile and Auto Components'")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    candidates = instruments.symbols_by_industry(args.industry, limit=args.limit)
    result = {
        "industry": args.industry,
        "as_of": args.as_of,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "source": f"local instruments master ({instruments.meta().get('built_at', 'unknown build time')})",
    }

    if not candidates:
        result["note"] = (
            "No matches — industry label must match exactly as stored (Nifty 500 coverage "
            "only). Ask the user to confirm the label rather than guessing a close spelling."
        )

    out_dir = Path.cwd() / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"candidates_{_slug(args.industry)}_{args.as_of}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(result, indent=2))
