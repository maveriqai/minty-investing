"""Unit tests for .claude/skills/screen-indian-stocks/scripts/screen_rank.py::compute.

Pure function tests against small synthetic candidate/fundamentals/quotes
fixtures — no network, no DB.
"""

import importlib.util
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent.parent / ".claude" / "skills" / "screen-indian-stocks" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sr = _load("screen_rank", _SCRIPTS_DIR / "screen_rank.py")


def _candidate(symbol: str, name: str = "Some Co") -> dict:
    return {"symbol": symbol, "name": name}


def test_candidate_with_no_fundamentals_file_is_excluded_with_reason():
    result = sr.compute([_candidate("NOFETCH")], fundamentals_by_symbol={})
    assert result["ranked"] == []
    assert result["excluded"] == [{"symbol": "NOFETCH", "reason": "no fundamentals data fetched for this candidate"}]


def test_candidate_with_fundamentals_error_is_excluded_with_reason():
    result = sr.compute(
        [_candidate("BROKEN")],
        fundamentals_by_symbol={"BROKEN": {"error": "yfinance timeout"}},
    )
    assert result["excluded"] == [{"symbol": "BROKEN", "reason": "fundamentals error: yfinance timeout"}]


def test_candidate_missing_pe_or_roe_is_excluded_not_ranked():
    result = sr.compute(
        [_candidate("NOPE")],
        fundamentals_by_symbol={"NOPE": {"trailing_pe": None, "return_on_equity_pct": 12.0}},
    )
    assert result["ranked"] == []
    assert result["excluded"][0]["reason"] == "missing or non-positive trailing_pe, or missing return_on_equity_pct"


def test_negative_pe_is_excluded_not_ranked_as_cheap():
    result = sr.compute(
        [_candidate("LOSSMAKER")],
        fundamentals_by_symbol={"LOSSMAKER": {"trailing_pe": -5.0, "return_on_equity_pct": 10.0}},
    )
    assert result["ranked"] == []
    assert result["excluded_count"] == 1


def test_high_leverage_flag_set_above_two_x_debt_to_equity():
    result = sr.compute(
        [_candidate("LEVERED")],
        fundamentals_by_symbol={
            "LEVERED": {"trailing_pe": 10.0, "return_on_equity_pct": 15.0, "debt_to_equity": 250.0}
        },
    )
    assert result["ranked"][0]["high_leverage_flag"] is True


def test_low_leverage_flag_not_set_at_or_below_two_x_debt_to_equity():
    result = sr.compute(
        [_candidate("SAFE")],
        fundamentals_by_symbol={"SAFE": {"trailing_pe": 10.0, "return_on_equity_pct": 15.0, "debt_to_equity": 150.0}},
    )
    assert result["ranked"][0]["high_leverage_flag"] is False


def test_ranking_favors_lower_pe_and_higher_roe():
    fundamentals = {
        "CHEAP_HIGH_ROE": {"trailing_pe": 8.0, "return_on_equity_pct": 25.0},
        "EXPENSIVE_LOW_ROE": {"trailing_pe": 40.0, "return_on_equity_pct": 5.0},
    }
    result = sr.compute(
        [_candidate("CHEAP_HIGH_ROE"), _candidate("EXPENSIVE_LOW_ROE")],
        fundamentals_by_symbol=fundamentals,
    )
    assert [r["symbol"] for r in result["ranked"]] == ["CHEAP_HIGH_ROE", "EXPENSIVE_LOW_ROE"]


def test_quote_attached_by_bare_symbol_stripping_ns_suffix():
    result = sr.compute(
        [_candidate("RELIANCE")],
        fundamentals_by_symbol={"RELIANCE": {"trailing_pe": 20.0, "return_on_equity_pct": 10.0}},
        quotes=[{"symbol": "RELIANCE.NS", "last_price": 2500.0, "day_change_pct": 0.5}],
    )
    assert result["ranked"][0]["last_price"] == 2500.0
    assert result["ranked"][0]["day_change_pct"] == 0.5


def test_quote_with_error_is_ignored_not_attached():
    result = sr.compute(
        [_candidate("RELIANCE")],
        fundamentals_by_symbol={"RELIANCE": {"trailing_pe": 20.0, "return_on_equity_pct": 10.0}},
        quotes=[{"symbol": "RELIANCE.NS", "error": "no data"}],
    )
    assert result["ranked"][0]["last_price"] is None


def test_no_quotes_at_all_still_ranks_on_fundamentals_alone():
    result = sr.compute(
        [_candidate("RELIANCE")],
        fundamentals_by_symbol={"RELIANCE": {"trailing_pe": 20.0, "return_on_equity_pct": 10.0}},
        quotes=None,
    )
    assert result["ranked"][0]["last_price"] is None
    assert result["ranked_count"] == 1
