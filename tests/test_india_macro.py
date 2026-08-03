"""Smoke tests for the india_macro MCP server.

Offline: rbi_fetch.rbi_get_text and exchange_calendar.get_segment_holidays
are monkeypatched so these never touch the network. Live-endpoint
verification (RBI current-rates HTML shape, NSE holiday-master response)
was done manually — see the server module docstring for what was verified
live on 2026-07-08.

`server` is loaded via importlib under a unique module name, not sys.path +
`import server` — see test_india_price.py / test_india_filings.py for why.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import exchange_calendar  # noqa: E402
import rbi_fetch  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("india_macro_server", Path(__file__).parent.parent / "mcp" / "india_macro" / "server.py")

SAMPLE_RATES_HTML = """
<h3 class="accordionButton"><a role="button">Policy&nbsp; Rates</a></h3>
<div class="accordionContent">
<table><tr><th>Policy Repo Rate</th><td>: 5.25%</td></tr>
<tr><th>Standing Deposit Facility Rate</th><td>: 5.00%</td></tr>
<tr><th>CRR</th><td>: 3.00%</td></tr></table>
</div>
<h3 class="accordionButton"><a role="button">Exchange &nbsp;Rates</a></h3>
<div class="accordionContent"><table><tr><th>INR / 1 USD</th><td>: 95.22</td></tr></table></div>
"""


def test_get_policy_rates_parses_table(monkeypatch):
    monkeypatch.setattr(rbi_fetch, "rbi_get_text", lambda path: SAMPLE_RATES_HTML)
    out = server.get_policy_rates()
    assert out["source"] == "RBI current-rates"
    assert out["data"]["Policy Repo Rate"] == "5.25%"
    assert out["data"]["CRR"] == "3.00%"
    assert "INR / 1 USD" not in out["data"]  # bounded to Policy Rates section, not FX


def test_get_policy_rates_surfaces_fetch_failure(monkeypatch):
    def _boom(path):
        raise RuntimeError("RBI fetch failed for /web/rbi/-/current-rates: timeout")

    monkeypatch.setattr(rbi_fetch, "rbi_get_text", _boom)
    out = server.get_policy_rates()
    assert "error" in out["data"]


def test_get_policy_rates_surfaces_unparseable_layout(monkeypatch):
    monkeypatch.setattr(rbi_fetch, "rbi_get_text", lambda path: "<html>no rates here</html>")
    out = server.get_policy_rates()
    assert "error" in out["data"]


def test_get_exchange_holidays_shape(monkeypatch):
    monkeypatch.setattr(
        exchange_calendar,
        "get_segment_holidays",
        lambda segment="CM": [{"date": "2026-01-26", "week_day": "Monday", "description": "Republic Day"}],
    )
    out = server.get_exchange_holidays("CM")
    assert out["source"] == "NSE holiday-master"
    assert out["data"]["segment"] == "CM"
    assert out["data"]["holidays"][0]["date"] == "2026-01-26"


def test_get_exchange_holidays_surfaces_unknown_segment(monkeypatch):
    def _boom(segment="CM"):
        raise KeyError("unknown segment 'ZZ', known: ['CM', 'FO']")

    monkeypatch.setattr(exchange_calendar, "get_segment_holidays", _boom)
    out = server.get_exchange_holidays("ZZ")
    assert "error" in out["data"]


def test_get_expiry_calendar_last_thursday_no_holiday(monkeypatch):
    monkeypatch.setattr(exchange_calendar, "get_segment_holidays", lambda segment="FO": [])
    out = server.get_expiry_calendar(2026, 7)
    # July 2026's last Thursday is the 30th.
    assert out["data"]["expiry_date"] == "2026-07-30"
    assert out["data"]["moved_from_last_thursday"] is False


def test_get_expiry_calendar_adjusts_for_holiday(monkeypatch):
    monkeypatch.setattr(
        exchange_calendar,
        "get_segment_holidays",
        lambda segment="FO": [{"date": "2026-07-30", "week_day": "Thursday", "description": "test holiday"}],
    )
    out = server.get_expiry_calendar(2026, 7)
    assert out["data"]["expiry_date"] == "2026-07-29"
    assert out["data"]["moved_from_last_thursday"] is True
    assert out["data"]["holiday_adjustment_reliable"] is True


@pytest.mark.network
def test_live_policy_rates():
    out = server.get_policy_rates()
    assert "error" not in out["data"]
    assert "Policy Repo Rate" in out["data"]


@pytest.mark.network
def test_live_exchange_holidays():
    out = server.get_exchange_holidays("CM")
    assert len(out["data"]["holidays"]) > 0
