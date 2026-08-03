"""Shared local instruments-master lookup (Layer 2 reference data).

Read-only accessor for the SQLite cache built by
`ingest/build_instruments_master.py` (symbol/exchange -> name, ISIN,
industry). Any MCP server or script needing symbol metadata should import
from here rather than querying Kite/NSE directly — this is the single
git-ignored local cache, refreshed by ingest/, never by a live session in a
loop (CLAUDE.md's "be polite to data sources" rule).

Note: the top-level `mcp/` directory name collides with the installed `mcp`
PyPI SDK package, so `import mcp.common.instruments` resolves to the SDK,
not this file. Import it the way tests/test_india_price.py imports server.py
instead: `sys.path.insert(0, "<repo-root>/mcp/common")` then `import
instruments`.

Industry/sector coverage is Nifty 500 constituents only (see the ingest
script's docstring) — `industry_for()` returns None for anything outside
that list, which is most small/micro-cap names. Don't treat a None as "no
sector"; treat it as "not yet covered."
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "instruments.db"


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} not found — run `uv run python ingest/build_instruments_master.py` first."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def meta() -> dict[str, str]:
    """Provenance for this local cache (built_at, source URLs, row counts) — for Sources footers."""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {r["key"]: r["value"] for r in rows}


def lookup(symbol: str, exchange: str = "NSE") -> dict[str, Any] | None:
    """Exact symbol+exchange lookup. Returns None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM instruments WHERE symbol = ? AND exchange = ?",
            (symbol.strip().upper(), exchange.strip().upper()),
        ).fetchone()
    return dict(row) if row else None


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fuzzy company-name or symbol search, NSE-first ordering."""
    like = f"%{query.strip().upper()}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM instruments
            WHERE symbol LIKE ? OR name LIKE ?
            ORDER BY exchange = 'NSE' DESC, symbol
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def industry_for(symbol: str, exchange: str = "NSE") -> str | None:
    """Sector/industry for a symbol, or None if outside Nifty 500 coverage (see module docstring)."""
    row = lookup(symbol, exchange)
    return row["industry"] if row else None


def symbols_by_industry(industry: str, limit: int = 50) -> list[dict[str, Any]]:
    """NSE symbols tagged with an exact industry label (see module docstring — Nifty 500 coverage only).

    industry: must match a label exactly as stored (e.g. "Automobile and
    Auto Components", "Financial Services") — this is a plain equality
    filter, not a fuzzy search like `search()`. Ordered by symbol, capped at
    `limit`. Used by screen-indian-stocks to build a candidate universe for
    a sector/theme without scanning the full ~22k-row instruments table.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM instruments WHERE industry = ? AND exchange = 'NSE' ORDER BY symbol LIMIT ?",
            (industry.strip(), limit),
        ).fetchall()
    return [dict(r) for r in rows]
