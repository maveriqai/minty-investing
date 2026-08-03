"""Smoke tests for mcp/common/instruments.py — the local instruments-master lookup.

Offline: builds a tiny throwaway SQLite DB (not the real data/instruments.db,
which is git-ignored and may not exist in a fresh checkout) and points the
module at it via monkeypatch. The real ingest run is exercised separately,
manually, since it hits live network endpoints.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import instruments  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "instruments.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE instruments (
            symbol TEXT NOT NULL, exchange TEXT NOT NULL, name TEXT, isin TEXT,
            industry TEXT, instrument_type TEXT, segment TEXT,
            instrument_token INTEGER, lot_size INTEGER, tick_size REAL,
            PRIMARY KEY (symbol, exchange)
        )
        """
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("RELIANCE", "NSE", "RELIANCE INDUSTRIES", "INE002A01018",
             "Oil Gas & Consumable Fuels", "EQ", "NSE", 738561, 1, 0.1),
            ("STOCKA", "NSE", "STOCKA", None, None, "EQ", "NSE", 4741121, 1, 0.01),
            ("MARUTI", "NSE", "MARUTI SUZUKI", "INE585B01010",
             "Automobile and Auto Components", "EQ", "NSE", 2815745, 1, 0.05),
            ("TATAMOTORS", "NSE", "TATA MOTORS", "INE155A01022",
             "Automobile and Auto Components", "EQ", "NSE", 884737, 1, 0.05),
        ],
    )
    conn.executemany("INSERT INTO meta VALUES (?, ?)", [("row_count", "2"), ("built_at", "test")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(instruments, "DB_PATH", path)
    return path


def test_lookup_found(db):
    row = instruments.lookup("reliance")
    assert row["name"] == "RELIANCE INDUSTRIES"
    assert row["industry"] == "Oil Gas & Consumable Fuels"


def test_lookup_missing(db):
    assert instruments.lookup("NOTASYMBOL") is None


def test_industry_for_covers_gap_honestly(db):
    assert instruments.industry_for("RELIANCE") == "Oil Gas & Consumable Fuels"
    assert instruments.industry_for("STOCKA") is None  # outside Nifty 500, not "unknown"


def test_search_matches_name_or_symbol(db):
    results = instruments.search("reliance")
    assert any(r["symbol"] == "RELIANCE" for r in results)


def test_meta(db):
    assert instruments.meta()["row_count"] == "2"


def test_symbols_by_industry_exact_match(db):
    results = instruments.symbols_by_industry("Automobile and Auto Components")
    symbols = {r["symbol"] for r in results}
    assert symbols == {"MARUTI", "TATAMOTORS"}


def test_symbols_by_industry_respects_limit(db):
    results = instruments.symbols_by_industry("Automobile and Auto Components", limit=1)
    assert len(results) == 1


def test_symbols_by_industry_no_match_returns_empty(db):
    assert instruments.symbols_by_industry("Not A Real Industry") == []


def test_missing_db_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(instruments, "DB_PATH", tmp_path / "nope.db")
    with pytest.raises(FileNotFoundError, match="build_instruments_master"):
        instruments.lookup("RELIANCE")
