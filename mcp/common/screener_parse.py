"""Pure HTML -> data parser for Screener.in company pages. No network I/O.

`has_financial_data()` and `parse_fundamentals()` implement rollout plan
step 2 (docs/screener-integration-design.md §12), built and tested against
the real fixtures in tests/fixtures/screener_*.html. Kept in its own
module, pure (HTML string in, typed data out), so it's directly testable
against saved fixtures without mocking a network client (§8-§10).

Fail-loud contract (§8): ScreenerParseError is raised when a container
Screener is expected to render is present but its internal shape doesn't
match what the parser expects (a markup change) — distinct from genuine
data absence (a field simply not shown for a given company, or an entire
optional section a young/thinly-covered company doesn't have), which stays
soft and becomes None, not an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Screener's top ratio-card <li> labels (span.name text) mapped to our field
# names — see design doc §8 for why market_cap_inr/book_value_per_share are
# deliberately aligned with india_price.get_fundamentals' field names while
# roe_pct stays deliberately distinct from return_on_equity_pct.
_RATIO_FIELD_MAP = {
    "Market Cap": "market_cap_inr",
    "Stock P/E": "trailing_pe",
    "Book Value": "book_value_per_share",
    "Dividend Yield": "dividend_yield_pct",
    "ROCE": "roce_pct",
    "ROE": "roe_pct",
    "Face Value": "face_value",
}

# The "Return on Equity" ranges-table's row labels, in the fixed order
# Screener renders them, mapped to our field names.
_ROE_TREND_FIELD_MAP = {
    "10 Years:": "roe_10yr_avg_pct",
    "5 Years:": "roe_5yr_avg_pct",
    "3 Years:": "roe_3yr_avg_pct",
    "Last Year:": "roe_last_year_pct",
}

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class ScreenerParseError(RuntimeError):
    """Screener rendered a container we expected to parse, but its shape
    didn't match — likely a markup change, not genuine data absence. See
    the Screener.in integration design doc §8 for the fail-loud/soft-absence
    distinction this error exists to encode."""

    def __init__(self, message: str, *, slug: str | None = None, section: str | None = None):
        super().__init__(message)
        self.slug = slug
        self.section = section


@dataclass
class Fundamentals:
    """Typed result of parse_fundamentals() — fields per design doc §8."""

    market_cap_inr: float | None
    trailing_pe: float | None
    book_value_per_share: float | None
    dividend_yield_pct: float | None
    roce_pct: float | None
    roe_pct: float | None
    face_value: float | None
    roe_10yr_avg_pct: float | None
    roe_5yr_avg_pct: float | None
    roe_3yr_avg_pct: float | None
    roe_last_year_pct: float | None
    consolidation: str  # "consolidated" | "standalone (no consolidated data available)"


def has_financial_data(html: str) -> bool:
    """True if the page's #profit-loss/#quarters tables carry real period
    columns, not just the empty corner header cell.

    Used by the fetch orchestration (§8, §11) to detect Screener's
    data-less consolidated scaffold (e.g. a company with no subsidiaries —
    the section renders with `<thead><tr><th></th></tr></thead>`, no period
    columns) and fall back to fetching the standalone URL instead. A probe,
    not a full parse — cheap to run even though this module doesn't
    otherwise extract #profit-loss/#quarters contents.
    """
    soup = BeautifulSoup(html, "html.parser")
    for section_id in ("profit-loss", "quarters"):
        section = soup.find(id=section_id)
        if section is None:
            continue
        thead = section.find("thead")
        if thead is None:
            continue
        if len(thead.find_all("th")) > 1:
            return True
    return False


def _parse_number(text: str) -> float | None:
    """"9%" -> 9.0, "-6%" -> -6.0, "" / "-" (Screener's no-data dash) -> None."""
    match = _NUMBER_RE.search(text)
    return float(match.group()) if match else None


def _parse_top_ratios(soup: BeautifulSoup, slug: str) -> dict[str, float | None]:
    ul = soup.find("ul", id="top-ratios")
    if ul is None:
        raise ScreenerParseError("top-ratios container not found", slug=slug, section="top-ratios")

    by_label: dict[str, float | None] = {}
    for li in ul.find_all("li"):
        name_span = li.find("span", class_="name")
        value_span = li.find("span", class_="nowrap value")
        if name_span is None or value_span is None:
            raise ScreenerParseError(
                "a top-ratios row is missing its expected name/value markup",
                slug=slug,
                section="top-ratios",
            )
        label = name_span.get_text(strip=True)
        number_span = value_span.find("span", class_="number")
        if number_span is None:
            # Genuinely no value shown for this ratio — soft, not an error.
            by_label[label] = None
            continue
        num = _parse_number(number_span.get_text(strip=True).replace(",", ""))
        if num is not None and "Cr." in value_span.get_text(" ", strip=True):
            num *= 1e7  # crores -> raw rupees, matching india_price's units (§8)
        by_label[label] = num
    return by_label


def _parse_roe_trend(soup: BeautifulSoup, slug: str) -> dict[str, float | None]:
    empty = dict.fromkeys(_ROE_TREND_FIELD_MAP.values())
    header = soup.find(lambda tag: tag.name == "th" and tag.get_text(strip=True) == "Return on Equity")
    if header is None:
        # A young/thinly-covered company without this section at all —
        # genuine absence, stays soft (§8).
        return empty

    table = header.find_parent("table")
    if table is None:
        raise ScreenerParseError(
            "a 'Return on Equity' header was found outside its expected table",
            slug=slug,
            section="roe-trend",
        )

    rows: dict[str, str] = {}
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            rows[tds[0].get_text(strip=True)] = tds[1].get_text(strip=True)

    result: dict[str, float | None] = {}
    for row_label, field in _ROE_TREND_FIELD_MAP.items():
        if row_label not in rows:
            raise ScreenerParseError(
                f"'Return on Equity' table is missing its expected {row_label!r} row",
                slug=slug,
                section="roe-trend",
            )
        result[field] = _parse_number(rows[row_label])
    return result


def parse_fundamentals(slug: str, html: str, *, consolidation: str) -> Fundamentals:
    """Parse a Screener company page into typed Fundamentals.

    `consolidation` is set by the caller from the fetch-with-fallback result
    (§8, §11), not inferred here — this function only reads the page it's
    handed. Raises ScreenerParseError per the fail-loud contract (module
    docstring) on a shape the parser failed to read; leaves a field None on
    genuine absence.
    """
    soup = BeautifulSoup(html, "html.parser")
    ratios = _parse_top_ratios(soup, slug)
    roe_trend = _parse_roe_trend(soup, slug)
    fields = {field: ratios.get(label) for label, field in _RATIO_FIELD_MAP.items()}
    fields.update(roe_trend)
    return Fundamentals(consolidation=consolidation, **fields)
