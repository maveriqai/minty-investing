"""Unit tests for skills/morning-digest/scripts/materiality_check.py::compute.

Pure function tests against small synthetic digest/news/announcement
envelope fixtures — no network, no real portfolio data. Sector resolution
is stubbed (mcp/common/sector_materiality.sector_for is already covered by
tests/test_sector_materiality.py) so these tests stay focused on the
bounded-symbol-set/scoring/ranking logic specific to this script.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent / ".claude" / "skills" / "morning-digest" / "scripts")
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load(
    "materiality_check",
    Path(__file__).parent.parent / ".claude" / "skills" / "morning-digest" / "scripts" / "materiality_check.py",
)


def _envelope(data):
    return {"source": "test", "as_of": "2026-07-21", "data": data}


def _stub_resolver(sector_by_symbol):
    def resolver(symbol):
        return sector_by_symbol.get(symbol, (None, "uncovered"))

    return resolver


DIGEST = {
    "top_concentration": [
        {"symbol": "STOCKA", "weight_pct": 28.4},
        {"symbol": "TCS", "weight_pct": 2.1},
    ],
    "day_gainers_by_pct": [
        {"symbol": "IEX", "weight_pct": 0.5},
    ],
    "day_losers_by_pct": [
        {"symbol": "TCS", "weight_pct": 2.1},  # overlaps top_concentration on purpose
    ],
}


def test_bounded_symbol_set_is_union_deduped():
    weights = mc._bounded_symbols(DIGEST)
    assert set(weights) == {"STOCKA", "TCS", "IEX"}
    assert weights["TCS"] == 2.1  # first occurrence wins, not overwritten by the dup


def test_missing_news_and_announcement_files_are_honest_gaps_not_a_crash():
    result = mc.compute(DIGEST, news_payloads={}, announcement_payloads={}, sector_resolver=_stub_resolver({}))
    assert result["flags"] == []
    assert set(result["symbols_no_news_data"]) == {"STOCKA", "TCS", "IEX"}
    assert set(result["symbols_no_announcement_data"]) == {"STOCKA", "TCS", "IEX"}


def test_upstream_tool_error_envelope_treated_as_missing_not_a_crash():
    news = {"STOCKA": {"source": "test", "as_of": "x", "data": {"error": "circuit open"}}}
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads={}, sector_resolver=_stub_resolver({}))
    assert "STOCKA" in result["symbols_no_news_data"]
    assert result["flags"] == []


def test_source_type_tagged_correctly_for_news_and_announcements():
    resolver = _stub_resolver({"STOCKA": (None, "yfinance")})
    news = {"STOCKA": _envelope([{"title": "Company sues supplier for breach", "link": "http://a"}])}
    ann = {"STOCKA": _envelope([{"desc": "Board approves acquisition of XYZ", "attchmntFile": "http://b"}])}
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads=ann, sector_resolver=resolver)

    source_types = {f["source_type"] for f in result["flags"]}
    assert source_types == {"news", "announcement"}
    news_flag = next(f for f in result["flags"] if f["source_type"] == "news")
    assert news_flag["link"] == "http://a"
    assert news_flag["sector_source"] == "yfinance"
    ann_flag = next(f for f in result["flags"] if f["source_type"] == "announcement")
    assert ann_flag["link"] == "http://b"


def test_sort_order_severity_then_weight():
    resolver = _stub_resolver({})
    news = {
        "STOCKA": _envelope([{"title": "Company sues supplier for breach"}]),  # litigation, high, weight 28.4
        "TCS": _envelope([{"title": "TCS wins order from client"}]),  # deal win via generic? no - IT sector needed
        "IEX": _envelope([{"title": "Company faces sebi order for penalty imposed"}]),  # regulatory order, high, weight 0.5
    }
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads={}, sector_resolver=resolver)
    severities = [f["severity"] for f in result["flags"]]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1}.get(s, 2))
    # among equal (high) severity, higher portfolio weight sorts first
    high_flags = [f for f in result["flags"] if f["severity"] == "high"]
    weights = [f["portfolio_weight_pct"] for f in high_flags]
    assert weights == sorted(weights, reverse=True)


def test_dedupe_collapses_same_symbol_same_signal_across_sources():
    resolver = _stub_resolver({})
    news = {
        "TCS": _envelope(
            [{"title": "TCS reports quarterly results with profit falling sharply amid demand headwinds"}]
        ),
    }
    ann = {
        "TCS": _envelope([{"desc": "board meeting outcome", "attchmntFile": "http://x"}]),
    }
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads=ann, sector_resolver=resolver)

    tcs_flags = [f for f in result["flags"] if f["symbol"] == "TCS"]
    assert len(tcs_flags) == 1
    assert tcs_flags[0]["source_type"] == "news"  # longer, more informative headline wins
    assert result["duplicate_flags_collapsed"] == 1


def test_dedupe_does_not_collapse_different_signals_for_same_symbol():
    resolver = _stub_resolver({})
    news = {
        "TCS": _envelope(
            [
                {"title": "TCS reports quarterly results with profit falling sharply"},
                {"title": "TCS faces sebi order for penalty imposed on disclosure lapse"},
            ]
        ),
    }
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads={}, sector_resolver=resolver)

    tcs_flags = [f for f in result["flags"] if f["symbol"] == "TCS"]
    assert len(tcs_flags) == 2
    assert result["duplicate_flags_collapsed"] == 0


def test_no_match_produces_no_flags():
    resolver = _stub_resolver({"IEX": ("Power & Utilities", "nse")})
    news = {"IEX": _envelope([{"title": "Company holds routine investor call"}])}
    result = mc.compute(DIGEST, news_payloads=news, announcement_payloads={}, sector_resolver=resolver)
    assert result["flag_count"] == 0
