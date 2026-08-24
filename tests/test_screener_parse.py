"""Offline tests for mcp/common/screener_parse.py, against real fixtures.

Rollout plan step 2 (docs/screener-integration-design.md §12): verify
has_financial_data() correctly triggers the consolidated -> standalone
fallback against the Gillette pair specifically, and pin the fail-loud vs.
soft-absence distinction (§8, §10) with synthetic minimal-HTML cases the
same way tests/parse/test_screener_parse.py in the PMB prior-art project
does — real fixtures prove the happy path and the fallback trigger; small
hand-built HTML snippets prove the parser's shape-violation/genuine-absence
discrimination without depending on ever finding a real malformed page.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "common"))

from screener_parse import (
    Fundamentals,
    ScreenerParseError,
    has_financial_data,
    parse_fundamentals,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestHasFinancialData:
    def test_apollo_consolidated_has_data(self):
        assert has_financial_data(_read("screener_apollotyre_consolidated.html")) is True

    def test_gillette_consolidated_has_no_data(self):
        # The blank-scaffold case (§11) — profit-loss/quarters sections
        # exist but their <thead> carries only the empty corner <th>.
        assert has_financial_data(_read("screener_gillette_consolidated.html")) is False

    def test_gillette_standalone_has_data(self):
        assert has_financial_data(_read("screener_gillette_standalone.html")) is True


class TestParseFundamentalsRealFixtures:
    def test_apollo_consolidated_happy_path(self):
        f = parse_fundamentals(
            "APOLLOTYRE", _read("screener_apollotyre_consolidated.html"), consolidation="consolidated"
        )
        assert isinstance(f, Fundamentals)
        assert f.consolidation == "consolidated"
        # Values as live-captured 2026-08-24 (design doc §8's own example),
        # allowing for later-day drift in market cap / price-derived fields.
        assert f.roce_pct == pytest.approx(13.9)
        assert f.roe_pct == pytest.approx(13.1)
        assert f.face_value == pytest.approx(1.00)
        assert f.roe_10yr_avg_pct == pytest.approx(9)
        assert f.roe_5yr_avg_pct == pytest.approx(10)
        assert f.roe_3yr_avg_pct == pytest.approx(12)
        assert f.roe_last_year_pct == pytest.approx(13)
        assert f.market_cap_inr > 1e11  # crores converted to raw rupees, not left as ~28000

    def test_gillette_standalone_fallback_target(self):
        f = parse_fundamentals(
            "GILLETTE",
            _read("screener_gillette_standalone.html"),
            consolidation="standalone (no consolidated data available)",
        )
        assert f.consolidation == "standalone (no consolidated data available)"
        assert f.roce_pct == pytest.approx(90.7)
        assert f.roe_pct == pytest.approx(66.5)
        assert f.roe_10yr_avg_pct == pytest.approx(39)
        assert f.roe_last_year_pct == pytest.approx(67)


class TestFailLoudContract:
    """Synthetic minimal-HTML cases, mirroring PMB's own test structure (§4,
    §10) — pins the shape-violation vs. genuine-absence line without
    depending on ever finding a real malformed page in the wild."""

    def _page(self, top_ratios: str = "", roe_trend: str = "") -> str:
        return f"""
        <html><body>
          <ul id="top-ratios">{top_ratios}</ul>
          <section id="profit-loss"></section>
          {roe_trend}
        </body></html>
        """

    _RATIO_LI = (
        '<li class="flex flex-space-between"><span class="name">ROE</span>'
        '<span class="nowrap value"><span class="number">13.1</span>%</span></li>'
    )

    _FULL_ROE_TABLE = """
        <table class="ranges-table">
          <tr><th colspan="2">Return on Equity</th></tr>
          <tr><td>10 Years:</td><td>9%</td></tr>
          <tr><td>5 Years:</td><td>10%</td></tr>
          <tr><td>3 Years:</td><td>12%</td></tr>
          <tr><td>Last Year:</td><td>13%</td></tr>
        </table>
    """

    def test_missing_top_ratios_container_raises(self):
        html = "<html><body><section id='profit-loss'></section></body></html>"
        with pytest.raises(ScreenerParseError) as ei:
            parse_fundamentals("acme", html, consolidation="consolidated")
        assert ei.value.slug == "acme"
        assert ei.value.section == "top-ratios"

    def test_malformed_ratio_row_raises(self):
        # A <li> with a name span but no value span at all — not a blank
        # value (which is soft), a structurally broken row.
        html = self._page(
            top_ratios='<li class="flex flex-space-between"><span class="name">ROE</span></li>',
            roe_trend=self._FULL_ROE_TABLE,
        )
        with pytest.raises(ScreenerParseError) as ei:
            parse_fundamentals("acme", html, consolidation="consolidated")
        assert ei.value.section == "top-ratios"

    def test_blank_ratio_value_stays_soft(self):
        # A real row, but Screener shows no number (dash placeholder /
        # empty span) for this company — genuine absence, not an error.
        html = self._page(
            top_ratios=(
                '<li class="flex flex-space-between"><span class="name">ROE</span>'
                '<span class="nowrap value">-</span></li>'
            ),
            roe_trend=self._FULL_ROE_TABLE,
        )
        f = parse_fundamentals("acme", html, consolidation="consolidated")
        assert f.roe_pct is None

    def test_missing_roe_trend_section_stays_soft(self):
        # No "Return on Equity" table anywhere — a young/thinly-covered
        # company without this history. Genuine absence, all four fields None.
        html = self._page(top_ratios=self._RATIO_LI, roe_trend="")
        f = parse_fundamentals("acme", html, consolidation="consolidated")
        assert f.roe_10yr_avg_pct is None
        assert f.roe_5yr_avg_pct is None
        assert f.roe_3yr_avg_pct is None
        assert f.roe_last_year_pct is None
        assert f.roe_pct == pytest.approx(13.1)  # unrelated field, unaffected

    def test_roe_trend_missing_one_period_raises(self):
        # The section exists, but is missing "Last Year:" — a shape the
        # parser expected and didn't get, not genuine absence.
        incomplete_table = """
            <table class="ranges-table">
              <tr><th colspan="2">Return on Equity</th></tr>
              <tr><td>10 Years:</td><td>9%</td></tr>
              <tr><td>5 Years:</td><td>10%</td></tr>
              <tr><td>3 Years:</td><td>12%</td></tr>
            </table>
        """
        html = self._page(top_ratios=self._RATIO_LI, roe_trend=incomplete_table)
        with pytest.raises(ScreenerParseError) as ei:
            parse_fundamentals("acme", html, consolidation="consolidated")
        assert ei.value.section == "roe-trend"

    def test_negative_roe_parses_with_sign(self):
        table_with_negative = """
            <table class="ranges-table">
              <tr><th colspan="2">Return on Equity</th></tr>
              <tr><td>10 Years:</td><td>9%</td></tr>
              <tr><td>5 Years:</td><td>10%</td></tr>
              <tr><td>3 Years:</td><td>12%</td></tr>
              <tr><td>Last Year:</td><td>-6%</td></tr>
            </table>
        """
        html = self._page(top_ratios=self._RATIO_LI, roe_trend=table_with_negative)
        f = parse_fundamentals("acme", html, consolidation="consolidated")
        assert f.roe_last_year_pct == pytest.approx(-6)
