"""Auto-captures raw Layer-2 MCP tool results into a workspace's `data/` —
removes "remember to save this with Write, using the right filename" as a
model responsibility. This is the raw-input-saving half of the skill-
adherence work started in `engine/skill_tools.py` (which covers the
compute-and-save half via typed deterministic-script tools).

Each entry maps one `(mcp_server, tool_name)` pair — as it appears in the
model's own namespaced tool name, `mcp__<server>__<tool>` — to the exact
filename convention each skill's `SKILL.md` prose and deterministic
scripts already document (e.g. `holdings_<date>.json`,
`shareholding_<SYMBOL>_<date>.json`). Filenames aren't invented here, so a
skill's own prose can keep citing the same path it always has — the model
just no longer has to save it there itself.

`india_price.get_quote` is the one tool called for two different purposes
within a single morning-digest run (index snapshot vs. every held symbol's
live price) — disambiguated by symbol shape: index tickers are always
"^"-prefixed (^NSEI, ^BSESN, ...), a stable convention already used
throughout this codebase, not a guess.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


_today = today_ist


def _symbol(args: dict[str, Any], key: str = "symbol") -> str:
    return str(args[key]).strip().upper()


def _quote_filename(args: dict[str, Any], today: str) -> str:
    symbols = args.get("symbols") or []
    if symbols and all(str(s).startswith("^") for s in symbols):
        return f"index_quote_{today}.json"
    return f"live_quotes_{today}.json"


FilenameFn = Callable[[dict[str, Any], str], str]

CAPTURE_SPECS: dict[tuple[str, str], FilenameFn] = {
    ("kite_gateway", "get_holdings"): lambda args, today: f"holdings_{today}.json",
    ("india_price", "get_quote"): _quote_filename,
    ("india_filings", "get_surveillance_list"): (
        lambda args, today: f"surveillance_{str(args.get('list_type', 'ASM')).strip().lower()}_{today}.json"
    ),
    ("india_filings", "get_announcements"): lambda args, today: f"announcements_{_symbol(args)}_{today}.json",
    ("india_news", "get_news"): lambda args, today: f"news_{_symbol(args, 'query')}_{today}.json",
    ("india_filings", "get_shareholding_pattern"): lambda args, today: f"shareholding_{_symbol(args)}_{today}.json",
    ("india_price", "get_fundamentals"): lambda args, today: f"fundamentals_{_symbol(args)}_{today}.json",
    ("india_price", "get_daily_ohlcv"): lambda args, today: f"{_symbol(args)}_ohlcv_1y.json",
    ("india_filings", "get_fii_dii_flows"): lambda args, today: f"fii_dii_{today}.json",
}


def parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    """"mcp__india_filings__get_announcements" -> ("india_filings", "get_announcements").

    None if `tool_name` isn't MCP-namespaced (a built-in tool like Read/Bash/Write).
    """
    prefix = "mcp__"
    if not tool_name.startswith(prefix):
        return None
    server, sep, tool = tool_name[len(prefix) :].partition("__")
    return (server, tool) if sep else None


def capture_path(tool_name: str, tool_input: dict[str, Any], workspace_root: Path) -> Path | None:
    """None if `tool_name` isn't a captured tool, or a required arg is missing from `tool_input`."""
    parsed = parse_mcp_tool_name(tool_name)
    if parsed is None:
        return None
    filename_fn = CAPTURE_SPECS.get(parsed)
    if filename_fn is None:
        return None
    try:
        filename = filename_fn(tool_input, _today())
    except (KeyError, TypeError):
        return None
    return workspace_root / "data" / filename


def save_tool_result(
    tool_name: str, tool_input: dict[str, Any], result_text: str, workspace_root: Path
) -> Path | None:
    """Writes `result_text` (the tool's own raw JSON text, unparsed) to its
    captured path, creating `data/` if needed. Returns the path written, or
    None if this tool isn't captured. Overwrites on repeat calls — freshest
    wins, matching a retried or re-fetched call always meaning "trust this
    one," never a reason to keep stale data around.
    """
    path = capture_path(tool_name, tool_input, workspace_root)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_text)
    return path


__all__ = ["capture_path", "parse_mcp_tool_name", "save_tool_result", "today_ist"]
