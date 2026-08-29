"""Build the local instruments master (Phase 1 step 2, Layer 2 reference data).

One-shot batch job — run by jobs/ or by hand, never called from an agent
session in a loop (CLAUDE.md's "be polite to data sources" rule). Combines
two verified, no-auth, publicly documented sources:

1. Kite's public instrument dump (https://api.kite.trade/instruments) — the
   full NSE+BSE cash-equity universe: symbol, name, exchange, lot size, tick
   size, instrument token. No ISIN, no sector.
2. NSE's Nifty 500 constituent list (industry classification + ISIN) — only
   covers the top ~500 names by market cap. Smaller/micro-cap names (e.g.
   STOCKA, a real held small-cap outside the Nifty 500) get industry=NULL.
   There is no verified
   free full-universe sector source yet — don't extend this to a broader NSE
   scrape without live-verifying the endpoint first; NSE's main site rejects
   most cookieless/default-User-Agent requests. See CLAUDE.md Open Decisions.

Writes data/instruments.db (git-ignored local cache) — an `instruments`
table plus a `meta` table (source URLs, build time, coverage count) so
callers can build a Sources footer without re-deriving provenance.

Usage: uv run python ingest/build_instruments_master.py
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "instruments.db"

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"
NSE_500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (Minty/0.1 research tool; local ingest job)"}


def _fetch_text(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_kite_universe() -> list[dict]:
    """Full NSE/BSE cash-equity universe from Kite's public instrument dump."""
    text = _fetch_text(KITE_INSTRUMENTS_URL)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["instrument_type"] != "EQ":
            continue
        if r["exchange"] not in ("NSE", "BSE") or r["segment"] != r["exchange"]:
            continue  # excludes INDICES/derivatives rows that share exchange="NSE"
        rows.append(
            {
                "symbol": r["tradingsymbol"].strip().upper(),
                "exchange": r["exchange"],
                "name": r["name"].strip(),
                "instrument_token": int(r["instrument_token"]),
                "lot_size": int(r["lot_size"]) if r["lot_size"] else None,
                "tick_size": float(r["tick_size"]) if r["tick_size"] else None,
                "instrument_type": r["instrument_type"],
                "segment": r["segment"],
            }
        )
    return rows


def fetch_nifty500_industry() -> dict[str, dict[str, str]]:
    """symbol -> {industry, isin} for Nifty 500 constituents (partial coverage, see module docstring)."""
    text = _fetch_text(NSE_500_URL)
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        symbol = r["Symbol"].strip().upper()
        out[symbol] = {"industry": r["Industry"].strip(), "isin": r["ISIN Code"].strip()}
    return out


def build() -> None:
    universe = fetch_kite_universe()
    industry_map = fetch_nifty500_industry()

    for row in universe:
        enrich = industry_map.get(row["symbol"])
        row["industry"] = enrich["industry"] if enrich else None
        row["isin"] = enrich["isin"] if enrich else None

    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS instruments")
    conn.execute(
        """
        CREATE TABLE instruments (
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            name TEXT,
            isin TEXT,
            industry TEXT,
            instrument_type TEXT,
            segment TEXT,
            instrument_token INTEGER,
            lot_size INTEGER,
            tick_size REAL,
            PRIMARY KEY (symbol, exchange)
        )
        """
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO instruments
        (symbol, exchange, name, isin, industry, instrument_type, segment,
         instrument_token, lot_size, tick_size)
        VALUES (:symbol, :exchange, :name, :isin, :industry, :instrument_type,
                :segment, :instrument_token, :lot_size, :tick_size)
        """,
        universe,
    )

    covered = sum(1 for r in universe if r["industry"])
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    conn.execute("DROP TABLE IF EXISTS meta")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [
            ("built_at", as_of),
            ("kite_source", KITE_INSTRUMENTS_URL),
            ("nse500_source", NSE_500_URL),
            ("row_count", str(len(universe))),
            ("industry_coverage_count", str(covered)),
        ],
    )
    conn.commit()
    conn.close()

    print(f"wrote {DB_PATH}")
    print(
        f"instruments={len(universe)}  industry_coverage={covered} "
        f"({covered / len(universe) * 100:.1f}%, Nifty 500 constituents only "
        "— industry labels are intentionally limited to Nifty 500 names, "
        "not a coverage failure)"
    )


if __name__ == "__main__":
    build()
