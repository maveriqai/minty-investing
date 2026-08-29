"""A typed SDK tool that looks up one symbol's holding record from the
workspace's already-cached holdings snapshot — issue #50.

`thesis-tracker` needs one symbol's quantity/average price, not the full
holdings list `fetch_holdings` (`engine/holdings_fetch.py`) writes to
`data/holdings_<date>.json`. That file is itself too large to `Read`
reliably (a 96-holding real account is ~80KB, sometimes serialized as one
line — see `holdings_fetch.py`'s own docstring) and thesis-tracker's
session only has `Read`/`Write` tools, no `Grep`/`Bash`, so there's no way
to search it either. Live-observed 2026-08-29: asked to track a thesis,
the model called `fetch_holdings` correctly, then tried hunting for one
symbol via repeated `Read` offset/limit guesses — every attempt failed.

Unlike `fetch_holdings`, this tool never calls Kite itself — it's a pure
read of whatever `fetch_holdings` already wrote for today (IST calendar
day, the same `holdings_<date>.json` naming convention). It deliberately
does not auto-fetch on a cache miss: that would duplicate
`holdings_fetch.py`'s Kite-calling/error-handling logic a second time, and
would mean silently hitting Kite on every thesis-tracker turn even when a
same-day cache already exists. Per issue #50's discussion, a cache miss
should prompt the user before refreshing, not auto-refresh or dead-end —
so this tool returns a `"no_cache"` status and leaves the ask-then-fetch
sequencing to the calling skill's own prose (`thesis-tracker/SKILL.md`
step 2), the same prompt-engineered level `check_identity_match`'s
`"mismatch"` case already uses for a comparable "stop and let the human
decide" moment.

Only ever reads today's exact date-stamped filename, never an older one —
so a multi-day-stale read is structurally impossible regardless of how the
miss case is handled.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.time_ist import today_ist
from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "NSE trading symbol to look up, e.g. RELIANCE — matched "
            "case-insensitively against Kite's tradingsymbol field.",
        },
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
    },
    "required": ["symbol", "workspace_root"],
}


async def _handler(args: dict[str, Any]) -> dict[str, Any]:
    workspace_root = _resolve_workspace_root(args.get("workspace_root", ""))
    if workspace_root is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"'workspace_root' must be an existing workspace directory — got {args.get('workspace_root')!r}",
                }
            ],
            "is_error": True,
        }

    today = today_ist()
    holdings_path = workspace_root / "data" / f"holdings_{today}.json"
    if not holdings_path.is_file():
        return {"content": [{"type": "text", "text": json.dumps({"status": "no_cache", "date": today})}]}

    try:
        envelope = json.loads(holdings_path.read_text())
    except json.JSONDecodeError:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"{holdings_path.name} is corrupted (not valid JSON) — call fetch_holdings to refresh it.",
                }
            ],
            "is_error": True,
        }

    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, list):
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"{holdings_path.name} isn't in the expected holdings shape — call fetch_holdings to refresh it.",
                }
            ],
            "is_error": True,
        }

    symbol = str(args.get("symbol", "")).strip().upper()
    as_of = envelope.get("as_of") if isinstance(envelope, dict) else None
    for holding in data:
        if isinstance(holding, dict) and str(holding.get("tradingsymbol", "")).strip().upper() == symbol:
            payload = {"status": "found", "symbol": symbol, "as_of": as_of, "holding": holding}
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    payload = {"status": "not_held", "symbol": symbol, "as_of": as_of}
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def build_holding_lookup_tool() -> SdkMcpTool[Any]:
    return tool(
        "get_holding_for_symbol",
        "Look up a single symbol's holding record from the workspace's cached "
        "holdings snapshot — call this instead of Reading data/holdings_<date>.json "
        "yourself (it can be too large) or calling kite_gateway.get_holdings "
        "(blocked, issue #46). Takes symbol and workspace_root. Returns "
        '{"status": "found", "holding": {...}} with the full matched record '
        '(quantity, average_price, etc. exactly as Kite returned it); '
        '{"status": "not_held", ...} if no cached holding matches (sold, '
        "delisted, or a typo — say so, don't guess); or "
        '{"status": "no_cache", "date": ...} if nothing has been fetched for '
        "today yet — in that case, ask the user whether to refresh (don't call "
        "fetch_holdings automatically), then call fetch_holdings and retry this "
        "tool if they say yes.",
        _INPUT_SCHEMA,
    )(_handler)


def build_holding_lookup_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="holding_lookup", tools=[build_holding_lookup_tool()])


__all__ = ["build_holding_lookup_server", "build_holding_lookup_tool"]
