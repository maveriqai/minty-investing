"""Smoke tests for the india_screener MCP server (rollout plan step 3).

Offline tests monkeypatch screener_fetch.screener_get against the real
fixtures captured in step 1, so the fetch-with-fallback orchestration (§8,
§11) is exercised end-to-end without hitting the network. One
`pytest -m network`-gated live test matches test_india_price.py's own
convention (test_daily_ohlcv_reliance).

Loaded via importlib under a unique module name — same import-collision
note as test_india_price.py: every mcp/<name>/ dir has its own server.py.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import screener_fetch

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("india_screener_server", Path(__file__).parent.parent / "mcp" / "india_screener" / "server.py")


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_consolidated_happy_path(monkeypatch):
    def fake_get(path, **kwargs):
        assert path == "/company/APOLLOTYRE/consolidated/"
        return _read("screener_apollotyre_consolidated.html")

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    out = server.get_fundamentals("apollotyre")
    assert out["source"] == "screener.in (scraped)"
    data = out["data"]
    assert data["symbol"] == "APOLLOTYRE"
    assert data["consolidation"] == "consolidated"
    assert data["roce_pct"] == pytest.approx(13.9)
    assert data["roe_pct"] == pytest.approx(13.1)
    assert "error" not in data


def test_ns_suffix_is_stripped_before_building_the_screener_url(monkeypatch):
    # india_price accepts a ".NS"/".BO" suffix; Screener's own slug never
    # carries one — a skill assuming symmetry between the two tools
    # shouldn't get a 404 for passing the same symbol form to both.
    def fake_get(path, **kwargs):
        assert path == "/company/APOLLOTYRE/consolidated/"
        return _read("screener_apollotyre_consolidated.html")

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    out = server.get_fundamentals("apollotyre.NS")
    assert out["data"]["symbol"] == "APOLLOTYRE"
    assert "error" not in out["data"]


def test_gillette_falls_back_to_standalone(monkeypatch):
    calls = []

    def fake_get(path, **kwargs):
        calls.append(path)
        if path == "/company/GILLETTE/consolidated/":
            return _read("screener_gillette_consolidated.html")
        assert path == "/company/GILLETTE/"
        return _read("screener_gillette_standalone.html")

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    out = server.get_fundamentals("GILLETTE")
    assert calls == ["/company/GILLETTE/consolidated/", "/company/GILLETTE/"]
    data = out["data"]
    assert data["consolidation"] == "standalone (no consolidated data available)"
    assert data["roce_pct"] == pytest.approx(90.7)
    assert data["roe_pct"] == pytest.approx(66.5)


def test_blocked_fetch_maps_to_data_error(monkeypatch):
    def fake_get(path, **kwargs):
        raise screener_fetch.ScreenerBlockedError("blocked")

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    out = server.get_fundamentals("APOLLOTYRE")
    assert "error" in out["data"]
    assert out["data"]["symbol"] == "APOLLOTYRE"


def test_circuit_open_maps_to_data_error(monkeypatch):
    def fake_get(path, **kwargs):
        raise screener_fetch.ScreenerCircuitOpenError("circuit open")

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    out = server.get_fundamentals("APOLLOTYRE")
    assert "error" in out["data"]


def test_parse_error_maps_to_data_error(monkeypatch):
    def fake_get(path, **kwargs):
        return "<html><body>unrecognizable shape</body></html>"

    monkeypatch.setattr(server.screener_fetch, "screener_get", fake_get)
    # has_financial_data() is False for this shape, so it also tries the
    # standalone leg — both return the same malformed page, both fail to
    # parse (missing #top-ratios), and the resulting ScreenerParseError
    # (a RuntimeError subclass) should map to data.error, not crash.
    out = server.get_fundamentals("APOLLOTYRE")
    assert "error" in out["data"]


@pytest.mark.network
def test_live_apollotyre_consolidated():
    out = server.get_fundamentals("APOLLOTYRE")
    data = out["data"]
    assert "error" not in data
    assert data["consolidation"] == "consolidated"
    assert isinstance(data["roe_pct"], float)
    assert isinstance(data["roce_pct"], float)
