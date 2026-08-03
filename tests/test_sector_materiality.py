"""Tests for mcp/common/sector_materiality.py — the shared materiality rubric.

Offline: yfinance is never actually hit — sector_materiality.yf.Ticker is
monkeypatched wherever the yfinance-fallback path is exercised.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

import instruments  # noqa: E402
import sector_materiality as sm  # noqa: E402


class _FakeTicker:
    def __init__(self, info):
        self.info = info


def test_every_nse_mapping_lands_in_a_real_bucket():
    for label, bucket in sm.NSE_TO_CANONICAL.items():
        assert bucket in sm.SECTOR_SIGNALS, f"{label} -> {bucket} has no signal content"


def test_every_yfinance_mapping_lands_in_a_real_bucket():
    for label, bucket in sm.YFINANCE_TO_CANONICAL.items():
        assert bucket in sm.SECTOR_SIGNALS, f"{label} -> {bucket} has no signal content"


def test_sector_for_prefers_nse_and_skips_yfinance(monkeypatch):
    monkeypatch.setattr(instruments, "industry_for", lambda symbol, exchange="NSE": "Financial Services")

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("yfinance should not be called when NSE already resolved")

    monkeypatch.setattr(sm.yf, "Ticker", _should_not_be_called)
    assert sm.sector_for("HDFCBANK") == ("Financial Services", "nse")


def test_sector_for_falls_back_to_yfinance_when_nse_misses(monkeypatch):
    monkeypatch.setattr(instruments, "industry_for", lambda symbol, exchange="NSE": None)
    monkeypatch.setattr(
        sm.yf, "Ticker", lambda ticker: _FakeTicker({"sector": "Consumer Defensive", "industry": "Household Products"})
    )
    assert sm.sector_for("CUPID") == ("FMCG & Consumer Staples", "yfinance")


def test_sector_for_disambiguates_basic_materials_by_industry(monkeypatch):
    monkeypatch.setattr(instruments, "industry_for", lambda symbol, exchange="NSE": None)
    monkeypatch.setattr(
        sm.yf, "Ticker", lambda ticker: _FakeTicker({"sector": "Basic Materials", "industry": "Specialty Chemicals"})
    )
    assert sm.sector_for("VINATIORGA") == ("Chemicals", "yfinance")

    monkeypatch.setattr(
        sm.yf, "Ticker", lambda ticker: _FakeTicker({"sector": "Basic Materials", "industry": "Steel"})
    )
    assert sm.sector_for("SANDUMA") == ("Metals & Mining", "yfinance")


def test_sector_for_fully_uncovered_returns_none_not_a_guess(monkeypatch):
    monkeypatch.setattr(instruments, "industry_for", lambda symbol, exchange="NSE": None)
    monkeypatch.setattr(sm.yf, "Ticker", lambda ticker: _FakeTicker({}))
    assert sm.sector_for("759KA38") == (None, "uncovered")


def test_sector_for_yfinance_network_error_is_uncovered_not_a_crash(monkeypatch):
    monkeypatch.setattr(instruments, "industry_for", lambda symbol, exchange="NSE": None)

    def _raise(ticker):
        raise Exception("network down")

    monkeypatch.setattr(sm.yf, "Ticker", _raise)
    assert sm.sector_for("GUJENERGY-BE") == (None, "uncovered")


def test_score_items_matches_its_own_sector_not_another():
    items = [{"title": "RBI cuts repo rate by 25bps"}]
    flags = sm.score_items("HDFCBANK", "Financial Services", items, ["title"])
    assert len(flags) == 1
    assert flags[0]["signal"] == "RBI policy action"

    # The same headline text scored against a different sector shouldn't
    # pick up a Financial-Services-specific signal.
    auto_flags = sm.score_items("MARUTI", "Automobile & Auto Components", items, ["title"])
    assert all(f["signal"] != "RBI policy action" for f in auto_flags)


def test_score_items_no_match_returns_empty_list():
    items = [{"title": "Company announces routine investor call schedule"}]
    assert sm.score_items("PAGEIND", "Consumer Discretionary", items, ["title"]) == []


def test_score_items_uncovered_sector_falls_back_to_generic():
    items = [{"title": "Company sues supplier for breach of contract"}]
    flags = sm.score_items("STOCKA", None, items, ["title"])
    assert any(f["signal"] == "Litigation" for f in flags)


def test_score_items_scores_announcement_fields_too():
    # Announcements use desc/attchmntText, not title (per red_flag_check.py's
    # existing field choice) — score_items must work against those too.
    items = [{"desc": "Board approves acquisition of XYZ Ltd", "attchmntText": ""}]
    flags = sm.score_items("HDFCBANK", "Financial Services", items, ["desc", "attchmntText"])
    assert any(f["signal"] == "M&A / stake change" for f in flags)


import re

_PREDICTIVE_OR_VALENCE_WORDS = [
    r"bullish", r"bearish", r"\bbuy\b", r"\bsell\b", r"outperform", r"underperform",
    r"likely to rise", r"likely to fall", r"expect the stock", r"will rally",
    r"target price", r"upside potential", r"downside risk",
]


def test_no_signal_rationale_contains_predictive_or_valence_language():
    all_signals = [sig for sigs in sm.SECTOR_SIGNALS.values() for sig in sigs] + sm.GENERIC_SIGNALS
    for sig in all_signals:
        rationale = sig["rationale"].lower()
        for pattern in _PREDICTIVE_OR_VALENCE_WORDS:
            assert not re.search(pattern, rationale), f"{sig['signal']!r} rationale matches {pattern!r}: {sig['rationale']!r}"
