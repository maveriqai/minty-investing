"""Minty india_news MCP server (Layer 2, added 2026-07-08 for red-flag-scan/screen-indian-stocks).

Free-text news search — the one thing missing from india_price (quotes/
fundamentals) and india_filings (structured NSE disclosures): neither
surfaces general business/market news or negative-sentiment coverage. Backed
by Google News RSS (mcp/common/news_fetch.py) — keyless, no registration,
query-based so the same tool serves a company-name lookup (red-flag-scan)
and a sector/theme phrase (screen-indian-stocks).

Results are headlines + links only, never full article text — narrate them
cautiously and cite the link, don't invent article content beyond the
headline given (CLAUDE.md's grounding rule). Every tool returns
{"source", "as_of", "data"} per the same Non-Negotiable Product Rules as
every other Layer 2 server.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import news_fetch  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("india_news")

IST = ZoneInfo("Asia/Kolkata")


def _envelope(data: Any, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def get_news(query: str, limit: int = 10) -> dict[str, Any]:
    """Recent news headlines matching a free-text query, via Google News RSS.

    query: for stock-specific news, the raw NSE trading symbol (e.g.
    "CUPID", not "Cupid Limited") — company name returns the same results,
    so only pass it if the symbol search comes back empty. For broader
    context, a theme/sector phrase (e.g. "Indian auto ancillary sector")
    works through the same search. limit: max items (default 10). Returns
    headlines/links/publish-time/publisher only, no article body text —
    don't narrate beyond what the headline says, and always cite the link.
    Use for red-flag scanning (negative-news keyword checks) or sector
    context, not as a substitute for india_filings' structured
    announcements.
    """
    try:
        items = news_fetch.news_search(query.strip(), limit=limit)
        return _envelope(items, "Google News RSS")
    except Exception as exc:  # noqa: BLE001 — circuit-open/fetch failure surfaced as a data gap, see module docstring
        return _envelope({"error": str(exc)}, "Google News RSS")


mcp.tool()(get_news)


if __name__ == "__main__":
    mcp.run()
