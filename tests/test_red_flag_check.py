"""Unit tests for skills/red-flag-scan/scripts/red_flag_check.py::compute.

Pure function tests against small synthetic tool-envelope fixtures — no
network, no DB. Shapes mirror what india_filings/india_news/india_price
actually return, verified live against STOCKA on 2026-07-08 (including the
ASM-is-nested-buckets vs. GSM-is-a-flat-list shape difference).
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent / ".claude" / "skills" / "red-flag-scan" / "scripts")
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rfc = _load(
    "red_flag_check",
    Path(__file__).parent.parent / ".claude" / "skills" / "red-flag-scan" / "scripts" / "red_flag_check.py",
)


def _envelope(data):
    return {"source": "test", "as_of": "2026-07-08", "data": data}


def test_no_inputs_skips_every_check():
    result = rfc.compute(symbol="stocka")
    assert result["symbol"] == "STOCKA"
    assert result["flags"] == []
    assert result["checks_performed"] == []
    assert set(result["checks_skipped"]) == {
        "promoter_holding",
        "asm_surveillance",
        "gsm_surveillance",
        "announcement_keywords",
        "news_keywords",
        "fundamentals_thresholds",
        "screener_roe_trend",
    }


def test_promoter_holding_decrease_flagged():
    shareholding = _envelope(
        [
            {"date": "31-MAR-2026", "pr_and_prgrp": "45.03"},
            {"date": "10-MAR-2026", "pr_and_prgrp": "45.95"},
        ]
    )
    result = rfc.compute(symbol="STOCKA", shareholding=shareholding)
    assert any(f["category"] == "promoter_holding_decrease" for f in result["flags"])


def test_promoter_holding_small_move_not_flagged():
    shareholding = _envelope(
        [
            {"date": "31-MAR-2026", "pr_and_prgrp": "45.90"},
            {"date": "10-MAR-2026", "pr_and_prgrp": "45.95"},
        ]
    )
    result = rfc.compute(symbol="STOCKA", shareholding=shareholding)
    assert result["flags"] == []
    assert "promoter_holding" in result["checks_performed"]


def test_asm_nested_bucket_shape_flags_matching_symbol():
    asm = _envelope(
        {
            "longterm": {"data": [{"symbol": "STOCKA", "survDesc": "LTASM Stage I"}]},
            "shortterm": {"data": []},
        }
    )
    result = rfc.compute(symbol="STOCKA", surveillance_asm=asm)
    assert any(f["category"] == "asm_surveillance" for f in result["flags"])


def test_gsm_flat_list_shape_flags_matching_symbol():
    gsm = _envelope([{"symbol": "STOCKA", "survDesc": "GSM Stage III"}])
    result = rfc.compute(symbol="STOCKA", surveillance_gsm=gsm)
    assert any(f["category"] == "gsm_surveillance" for f in result["flags"])


def test_surveillance_no_match_no_flag():
    asm = _envelope({"longterm": {"data": [{"symbol": "OTHERCO"}]}, "shortterm": {"data": []}})
    result = rfc.compute(symbol="STOCKA", surveillance_asm=asm)
    assert result["flags"] == []
    assert "asm_surveillance" in result["checks_performed"]


def test_announcement_keyword_match():
    announcements = _envelope(
        [{"desc": "Resignation of Auditor", "attchmntText": "The company informs..."}]
    )
    result = rfc.compute(symbol="STOCKA", announcements=announcements)
    assert any(f["category"] == "announcement_keyword" for f in result["flags"])


def test_news_keyword_match():
    news = _envelope([{"title": "Company X faces SEBI action over disclosure lapse"}])
    result = rfc.compute(symbol="STOCKA", news=news)
    assert any(f["category"] == "news_keyword" for f in result["flags"])


def test_fundamentals_high_leverage_and_liquidity_stress():
    # debt_to_equity is yfinance's percentage convention (verified against RELIANCE
    # reading 36.653 in prod, not a raw ratio) — 250 here means D/E ratio 2.5x.
    fundamentals = _envelope({"debt_to_equity": 250.0, "current_ratio": 0.5})
    result = rfc.compute(symbol="STOCKA", fundamentals=fundamentals)
    categories = {f["category"] for f in result["flags"]}
    assert categories == {"high_leverage", "liquidity_stress"}


def test_fundamentals_healthy_no_flags():
    fundamentals = _envelope({"debt_to_equity": 30.0, "current_ratio": 2.1})
    result = rfc.compute(symbol="STOCKA", fundamentals=fundamentals)
    assert result["flags"] == []


def test_upstream_tool_error_treated_as_missing_not_crash():
    broken = _envelope({"error": "circuit open"})
    result = rfc.compute(symbol="STOCKA", fundamentals=broken, announcements=broken)
    assert result["flags"] == []
    assert "fundamentals_thresholds" in result["checks_skipped"]
    assert "announcement_keywords" in result["checks_skipped"]


def test_screener_roe_deteriorating_flagged():
    fundamentals_screener = _envelope({"roe_last_year_pct": 5.0, "roe_3yr_avg_pct": 12.0})
    result = rfc.compute(symbol="STOCKA", fundamentals_screener=fundamentals_screener)
    assert any(f["category"] == "roe_deteriorating" for f in result["flags"])
    assert "screener_roe_trend" in result["checks_performed"]


def test_screener_roe_stable_not_flagged():
    fundamentals_screener = _envelope({"roe_last_year_pct": 13.0, "roe_3yr_avg_pct": 12.0})
    result = rfc.compute(symbol="STOCKA", fundamentals_screener=fundamentals_screener)
    assert result["flags"] == []
    assert "screener_roe_trend" in result["checks_performed"]


def test_screener_roe_missing_fields_stays_soft_no_crash():
    fundamentals_screener = _envelope({"roe_last_year_pct": None, "roe_3yr_avg_pct": None})
    result = rfc.compute(symbol="STOCKA", fundamentals_screener=fundamentals_screener)
    assert result["flags"] == []
    assert "screener_roe_trend" in result["checks_performed"]


def test_screener_fundamentals_error_treated_as_missing():
    broken = _envelope({"error": "Screener blocked"})
    result = rfc.compute(symbol="STOCKA", fundamentals_screener=broken)
    assert result["flags"] == []
    assert "screener_roe_trend" in result["checks_skipped"]
