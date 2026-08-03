"""Minty india_price MCP server (Layer 2).

Daily OHLCV, quotes, and market status for NSE/BSE equities and major Indian
indices. Phase-1 backend: yfinance (free, keyless, EOD-grade). Bhavcopy and
broker-API backends land later behind the same tool signatures — callers must
not assume yfinance-specific fields beyond the documented return shapes.

Tools:
- resolve_symbol:    fuzzy name/ticker -> candidate instruments
- get_daily_ohlcv:   daily bars for one equity
- get_index_ohlcv:   daily bars for a major index
- get_quote:         latest snapshot for one or more equities
- get_fundamentals:  trailing valuation/profitability ratios for one equity
- get_market_status: NSE session status (IST clock; holidays TODO)

Every tool returns {"source", "as_of", "data"} so outputs are provenance-ready.
Money math on this data happens in code (scripts/executor), never in the LLM —
see CLAUDE.md Non-Negotiable Product Rules.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import exchange_calendar  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("india_price")

IST = ZoneInfo("Asia/Kolkata")

# Known-good Yahoo symbols for major Indian indices.
INDEX_MAP: dict[str, str] = {
    "NIFTY50": "^NSEI",
    "NIFTY": "^NSEI",
    "SENSEX": "^BSESN",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYIT": "^CNXIT",
    "INDIAVIX": "^INDIAVIX",
}


def _norm(symbol: str) -> str:
    """Normalize an equity symbol to a Yahoo ticker (default NSE)."""
    s = symbol.strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return f"{s}.NS"


def _bars(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize a yfinance history frame to compact records."""
    if df is None or df.empty:
        return []
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "Datetime"
    def _num(v: Any) -> float | None:
        return round(float(v), 2) if pd.notna(v) else None

    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "date": pd.Timestamp(row[date_col]).strftime("%Y-%m-%d"),
                "open": _num(row["Open"]),
                "high": _num(row["High"]),
                "low": _num(row["Low"]),
                "close": _num(row["Close"]),
                "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            }
        )
    return out


def _envelope(data: Any, source: str = "yfinance") -> dict[str, Any]:
    return {
        "source": source,
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def resolve_symbol(query: str, limit: int = 5) -> dict[str, Any]:
    """Resolve a company name or partial ticker to candidate instruments.

    Use before other tools when you only have a company name (e.g. "asian
    paints" -> ASIANPAINT.NS). Returns candidates with symbol, name, and
    exchange. Prefer the .NS (NSE) listing unless the user asks for BSE.
    """
    try:
        results = yf.Search(query, max_results=limit).quotes
    except Exception as exc:  # network / API drift
        return _envelope({"error": f"search failed: {exc}", "candidates": []})
    candidates = [
        {
            "symbol": q.get("symbol"),
            "name": q.get("shortname") or q.get("longname"),
            "exchange": q.get("exchange"),
        }
        for q in results
        if str(q.get("symbol", "")).endswith((".NS", ".BO"))
    ]
    return _envelope({"query": query, "candidates": candidates})


def get_daily_ohlcv(symbol: str, from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    """Daily OHLCV bars for one NSE/BSE equity.

    symbol: ticker with or without suffix ("RELIANCE" -> RELIANCE.NS; use
    ".BO" explicitly for BSE). Dates are "YYYY-MM-DD"; defaults to the last
    1 year. Returns bars oldest-first. For index data use get_index_ohlcv.
    """
    ticker = _norm(symbol)
    end = to_date or datetime.now(IST).strftime("%Y-%m-%d")
    start = from_date or (datetime.now(IST) - timedelta(days=365)).strftime("%Y-%m-%d")
    df = yf.Ticker(ticker).history(start=start, end=end, interval="1d", auto_adjust=True)
    return _envelope({"symbol": ticker, "from": start, "to": end, "bars": _bars(df)})


def get_index_ohlcv(index: str, from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    """Daily OHLCV bars for a major Indian index.

    index: one of NIFTY50/NIFTY, SENSEX, BANKNIFTY, NIFTYIT, INDIAVIX — or a
    raw Yahoo index symbol starting with "^". Dates "YYYY-MM-DD", default
    last 1 year.
    """
    key = index.strip().upper().replace(" ", "")
    ticker = INDEX_MAP.get(key) or (key if key.startswith("^") else None)
    if ticker is None:
        return _envelope({"error": f"unknown index '{index}'", "known": sorted(set(INDEX_MAP))})
    end = to_date or datetime.now(IST).strftime("%Y-%m-%d")
    start = from_date or (datetime.now(IST) - timedelta(days=365)).strftime("%Y-%m-%d")
    df = yf.Ticker(ticker).history(start=start, end=end, interval="1d", auto_adjust=True)
    return _envelope({"index": index, "symbol": ticker, "from": start, "to": end, "bars": _bars(df)})


def get_quote(symbols: list[str]) -> dict[str, Any]:
    """Latest snapshot for one or more equities (delayed EOD-grade, not tick data).

    Returns last price, previous close, day change %, 52-week range, and
    market cap (INR) per symbol. For live intraday quotes prefer the Kite MCP
    when the user's session is connected.
    """
    quotes = []
    for sym in symbols:
        ticker = _norm(sym)
        try:
            fi = yf.Ticker(ticker).fast_info
            last = fi.get("lastPrice")
            prev = fi.get("previousClose")
            change_pct = round((last - prev) / prev * 100, 2) if last and prev else None
            quotes.append(
                {
                    "symbol": ticker,
                    "last_price": round(last, 2) if last else None,
                    "previous_close": round(prev, 2) if prev else None,
                    "day_change_pct": change_pct,
                    "year_high": fi.get("yearHigh"),
                    "year_low": fi.get("yearLow"),
                    "market_cap_inr": fi.get("marketCap"),
                }
            )
        except Exception as exc:
            quotes.append({"symbol": ticker, "error": str(exc)})
    return _envelope(quotes)


def get_fundamentals(symbol: str) -> dict[str, Any]:
    """Trailing valuation and profitability ratios for one NSE/BSE equity.

    symbol: ticker with or without suffix (e.g. "STOCKA" -> STOCKA.NS). Pulls
    yfinance's most recent reported figures (trailing twelve months unless
    noted) — these are exchange/company-reported numbers, not Minty
    calculations; narrate them as-is, don't re-derive ratios from them by
    LLM arithmetic. Some fields are None for thinly-covered small/micro-caps
    (Yahoo doesn't always carry forward estimates) — report gaps honestly
    rather than guessing. For a fuller picture pair with
    india_filings.get_announcements for the underlying results filing.
    """
    ticker = _norm(symbol)
    try:
        info = yf.Ticker(ticker).info
    except Exception as exc:  # network / API drift
        return _envelope({"symbol": ticker, "error": str(exc)})
    data = {
        "symbol": ticker,
        "market_cap_inr": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "trailing_eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),
        "price_to_book": info.get("priceToBook"),
        "book_value_per_share": info.get("bookValue"),
        "return_on_equity_pct": round(info["returnOnEquity"] * 100, 2) if info.get("returnOnEquity") is not None else None,
        "profit_margin_pct": round(info["profitMargins"] * 100, 2) if info.get("profitMargins") is not None else None,
        "operating_margin_pct": round(info["operatingMargins"] * 100, 2) if info.get("operatingMargins") is not None else None,
        "revenue_growth_pct": round(info["revenueGrowth"] * 100, 2) if info.get("revenueGrowth") is not None else None,
        "earnings_growth_pct": round(info["earningsGrowth"] * 100, 2) if info.get("earningsGrowth") is not None else None,
        "total_revenue_inr": info.get("totalRevenue"),
        "net_income_inr": info.get("netIncomeToCommon"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
    }
    return _envelope(data)


def get_market_status() -> dict[str, Any]:
    """NSE equity session status by IST clock (9:15–15:30, Mon–Fri) plus holidays.

    Holiday check is a live NSE lookup (mcp/common/exchange_calendar.py,
    shared with india_macro.get_exchange_holidays, cached ~6h) that fails
    open — if the holiday list can't be fetched, this degrades to a
    weekday/clock-only check (`holiday_calendar_loaded: False`) rather than
    raising, so a transient NSE outage never breaks a market-status check
    that used to have zero network dependency.
    """
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    is_weekday = now.weekday() < 5
    try:
        holidays = exchange_calendar.get_segment_holidays("CM")
        is_holiday = any(h["date"] == today for h in holidays)
        holiday_calendar_loaded = True
    except Exception:  # noqa: BLE001 — degrade to clock-only rather than fail the whole tool
        is_holiday = False
        holiday_calendar_loaded = False
    open_t, close_t = now.replace(hour=9, minute=15), now.replace(hour=15, minute=30)
    is_open = is_weekday and not is_holiday and open_t <= now <= close_t
    return _envelope(
        {
            "now_ist": now.strftime("%Y-%m-%d %H:%M"),
            "market": "NSE equity",
            "is_open": is_open,
            "session": "09:15–15:30 IST Mon–Fri",
            "holiday_calendar_loaded": holiday_calendar_loaded,
        },
        source="clock",
    )


# Registration kept separate so functions stay plainly importable in tests.
mcp.tool()(resolve_symbol)
mcp.tool()(get_daily_ohlcv)
mcp.tool()(get_index_ohlcv)
mcp.tool()(get_quote)
mcp.tool()(get_fundamentals)
mcp.tool()(get_market_status)


if __name__ == "__main__":
    mcp.run()
