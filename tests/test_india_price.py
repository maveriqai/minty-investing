"""Smoke tests for the india_price MCP server.

Offline tests run always; network tests are skipped unless yfinance can
reach Yahoo (kept out of the default fast path anyway — run with
`pytest -m network` deliberately).

Loaded via importlib under a unique module name rather than sys.path +
`import server` — every mcp/<name>/ dir has its own server.py, so a plain
`import server` collides across test files once more than one exists
(bit us when india_filings/server.py landed; see that test file too).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import exchange_calendar  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("india_price_server", Path(__file__).parent.parent / "mcp" / "india_price" / "server.py")


def test_norm_defaults_to_nse():
    assert server._norm("reliance") == "RELIANCE.NS"
    assert server._norm("RELIANCE.BO") == "RELIANCE.BO"
    assert server._norm("^NSEI") == "^NSEI"


def test_market_status_shape(monkeypatch):
    monkeypatch.setattr(exchange_calendar, "get_segment_holidays", lambda segment="CM": [])
    out = server.get_market_status()
    assert out["source"] == "clock"
    data = out["data"]
    assert data["market"] == "NSE equity"
    assert isinstance(data["is_open"], bool)
    assert data["holiday_calendar_loaded"] is True


def test_market_status_degrades_when_holiday_fetch_fails(monkeypatch):
    def _boom(segment="CM"):
        raise RuntimeError("NSE fetch failed")

    monkeypatch.setattr(exchange_calendar, "get_segment_holidays", _boom)
    out = server.get_market_status()
    assert out["data"]["holiday_calendar_loaded"] is False


def test_unknown_index_lists_known_ones():
    out = server.get_index_ohlcv("NOTANINDEX")
    assert "error" in out["data"]
    assert "SENSEX" in out["data"]["known"]


@pytest.mark.network
def test_daily_ohlcv_reliance():
    out = server.get_daily_ohlcv("RELIANCE", from_date="2026-06-22", to_date="2026-07-05")
    bars = out["data"]["bars"]
    assert len(bars) > 3
    assert {"date", "open", "high", "low", "close", "volume"} <= set(bars[0])
