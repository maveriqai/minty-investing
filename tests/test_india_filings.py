"""Smoke tests for the india_filings MCP server.

Offline: nse_fetch.nse_get is monkeypatched so these never touch the
network. Live-endpoint verification (including confirming bulk/block deals
is still down) is exercised separately, manually — see the server module
docstring for what was verified live on 2026-07-08.

`server` is loaded via importlib under a unique module name, not sys.path +
`import server` — every mcp/<name>/ dir has its own server.py, so a plain
`import server` collides across test files once more than one exists (see
test_india_price.py for the same fix).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import nse_fetch  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("india_filings_server", Path(__file__).parent.parent / "mcp" / "india_filings" / "server.py")


def test_get_announcements_shape(monkeypatch):
    calls = {}

    def fake_get(path, params=None, referer=""):
        calls["path"] = path
        calls["params"] = params
        return [{"symbol": "RELIANCE", "an_dt": "06-Jul-2026 17:17:52", "desc": "General Updates"}]

    monkeypatch.setattr(nse_fetch, "nse_get", fake_get)
    out = server.get_announcements("reliance", from_date="01-06-2026")
    assert out["source"] == "NSE corporate-announcements"
    assert calls["path"] == "/api/corporate-announcements"
    assert calls["params"] == {"index": "equities", "symbol": "RELIANCE", "from_date": "01-06-2026"}
    assert out["data"][0]["symbol"] == "RELIANCE"


def test_get_fii_dii_flows_no_symbol_arg(monkeypatch):
    monkeypatch.setattr(nse_fetch, "nse_get", lambda path, params=None, referer="": [{"category": "DII"}])
    out = server.get_fii_dii_flows()
    assert out["data"] == [{"category": "DII"}]


def test_get_surveillance_list_validates_type():
    out = server.get_surveillance_list("XYZ")
    assert "error" in out["data"]


def test_get_surveillance_list_routes_to_correct_endpoint(monkeypatch):
    calls = {}

    def fake_get(path, params=None, referer=""):
        calls["path"] = path
        return []

    monkeypatch.setattr(nse_fetch, "nse_get", fake_get)
    server.get_surveillance_list("gsm")
    assert calls["path"] == "/api/reportGSM"
    server.get_surveillance_list("asm")
    assert calls["path"] == "/api/reportASM"


def test_bulk_block_deals_surfaces_failure_honestly(monkeypatch):
    def fake_get(path, params=None, referer=""):
        raise RuntimeError("NSE fetch failed for /api/historical/bulk-deals: 503")

    monkeypatch.setattr(nse_fetch, "nse_get", fake_get)
    out = server.get_bulk_block_deals("RELIANCE")
    assert "error" in out["data"]
    assert "503" in out["data"]["error"]


def test_circuit_open_error_also_surfaces_as_data_error(monkeypatch):
    def fake_get(path, params=None, referer=""):
        raise nse_fetch.NSECircuitOpenError("circuit open")

    monkeypatch.setattr(nse_fetch, "nse_get", fake_get)
    out = server.get_announcements("RELIANCE")
    assert "circuit open" in out["data"]["error"]


@pytest.mark.network
def test_live_announcements_reliance():
    out = server.get_announcements("RELIANCE", from_date="01-06-2026", to_date="08-07-2026")
    assert len(out["data"]) > 0
    assert out["data"][0]["symbol"] == "RELIANCE"


@pytest.mark.network
def test_live_bulk_block_deals_known_down():
    """Documents the known outage rather than asserting success — see server module docstring."""
    out = server.get_bulk_block_deals("RELIANCE")
    assert "error" in out["data"]
