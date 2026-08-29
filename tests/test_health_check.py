"""Unit tests for .claude/skills/portfolio-health-check/scripts/health_check.py::compute.

Pure function tests against small synthetic holding fixtures — no network,
no real portfolio data.
"""

import importlib.util
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).parent.parent / ".claude" / "skills" / "portfolio-health-check" / "scripts" / "health_check.py"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hc = _load("health_check", _SCRIPT_PATH)


def _holding(symbol, quantity=10, average_price=100.0, last_price=100.0, exchange="NSE"):
    return {
        "tradingsymbol": symbol,
        "exchange": exchange,
        "quantity": quantity,
        "average_price": average_price,
        "last_price": last_price,
    }


def test_classify_asset_class_equity():
    assert hc._classify_asset_class("RELIANCE") == "Equity"


def test_classify_asset_class_bees_etf():
    assert hc._classify_asset_class("GOLDBEES") == "ETF"
    assert hc._classify_asset_class("NIFTYBEES") == "ETF"


def test_classify_asset_class_gs_suffix_gsec():
    assert hc._classify_asset_class("710GS2029-GS") == "G-Sec"


def test_classify_asset_class_sg_suffix_gsec():
    assert hc._classify_asset_class("754KA41-SG") == "G-Sec"


def test_classify_asset_class_digit_leading_unclassified():
    # A real held G-Sec (759KA38) has no distinguishing suffix at all —
    # must not be silently folded into Equity.
    assert hc._classify_asset_class("759KA38") == "Other (unclassified — possible bond/G-Sec)"


def test_compute_tags_each_row_with_asset_class():
    holdings = [_holding("RELIANCE"), _holding("GOLDBEES"), _holding("710GS2029-GS")]

    result = hc.compute(holdings)

    by_symbol = {r["symbol"]: r["asset_class"] for r in result["all_positions"]}
    assert by_symbol == {"RELIANCE": "Equity", "GOLDBEES": "ETF", "710GS2029-GS": "G-Sec"}


def test_compute_asset_class_breakdown_aggregates_value_and_weight():
    holdings = [
        _holding("RELIANCE", quantity=10, average_price=100.0, last_price=100.0),  # value 1000
        _holding("TCS", quantity=10, average_price=100.0, last_price=100.0),  # value 1000
        _holding("GOLDBEES", quantity=10, average_price=50.0, last_price=50.0),  # value 500
        _holding("759KA38", quantity=1, average_price=1000.0, last_price=1000.0),  # value 1000
    ]

    result = hc.compute(holdings)
    breakdown = result["asset_class_breakdown"]

    assert breakdown["Equity"]["value"] == 2000.0
    assert breakdown["Equity"]["position_count"] == 2
    assert breakdown["ETF"]["value"] == 500.0
    assert breakdown["ETF"]["position_count"] == 1
    assert breakdown["Other (unclassified — possible bond/G-Sec)"]["value"] == 1000.0
    total_value = result["total_value"]
    assert breakdown["Equity"]["weight_pct"] == round(2000.0 / total_value * 100, 2)
