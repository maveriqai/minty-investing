"""A typed SDK tool that fetches Kite holdings and saves them to the
workspace without ever passing the raw payload through the model's own
turn — issue #46.

On the real connected account (96 holdings, ~63k characters of JSON), the
Claude Agent SDK itself substitutes a plain-text "exceeds maximum allowed
tokens" message in place of the real tool result before it ever reaches
the engine — `engine/tool_capture.py`'s `_is_untrustworthy_capture`
already detects and rejects that redirect (case 2 in its docstring), which
is correct but means `data/holdings_<date>.json` never gets written at
all, and every skill that needs holdings (`portfolio-health-check`,
`morning-digest`) has nothing to work from. `get_holdings` takes no
arguments — Kite's real API returns everything in one unparameterized
call, so there's no server-side pagination to shrink the result with.

The only way to keep the payload out of the model's token budget is to
never hand it to the model at all: this tool calls Kite in-process and
writes straight to disk, returning only a short status. `get_holdings`
itself is fully blocked from the model's tool inventory
(`engine/harnesses/claude_agent_sdk.py`'s `disallowed_tools`) — this is
the only path to holdings data now, everywhere, not a second option next
to the broken one.

Reuses two existing code paths rather than reimplementing either:

1. `mcp/kite_gateway/server.py`'s `call_tool` — the same function a real
   MCP round trip already goes through (session persistence/TTL/retry,
   the `{"source","as_of","data"}` envelope). `@server.call_tool()` is a
   registration decorator that returns the original function unchanged,
   so it's directly awaitable once loaded. Loaded via
   `importlib.util.spec_from_file_location` rather than a normal import —
   see `_load_kite_gateway_server` below for why. This gives this process
   a second, independent `_Upstream` instance, coordinated with the
   standalone `kite_gateway` MCP subprocess only through the shared,
   file-persisted `SESSION_ID_FILE` — exactly the cross-process
   persistence model that module already documents itself as designed
   for, not a new coordination mechanism.
2. `engine.tool_capture.save_tool_result` — the exact same filename
   convention (`holdings_<date>.json`) and untrustworthy-result guard an
   ordinary capture already gets, so `run_health_check`/`digest_math.py`
   need zero changes to keep reading the same file.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.tool_capture import save_tool_result
from engine.workspace import REPO_ROOT
from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root

_TOOL_NAME = "mcp__kite_gateway__get_holdings"

_KITE_GATEWAY_SERVER_PATH = REPO_ROOT / "mcp" / "kite_gateway" / "server.py"


def _load_kite_gateway_server():
    """`mcp/` is never imported as a real Python package in this codebase
    (only `engine/` is — see CLAUDE.md's Conventions section) — `import
    mcp.kite_gateway.server` would collide with the actual installed `mcp`
    SDK package that `kite_gateway/server.py` itself depends on (`import
    mcp.types as types`, `from mcp.server import Server`, ...). Loaded via
    `importlib.util.spec_from_file_location` under a unique module name
    instead, the same pattern `tests/test_kite_gateway.py` already uses.
    Confirmed safe: `server.py`'s own imports are all absolute references
    to the real installed `mcp` package, never this repo's `mcp/common/`,
    so nothing here needs `mcp/` to be on `sys.path` as a package.

    Loaded once, at import time, not per call — a fresh module load would
    also mint a fresh in-process `_Upstream()` singleton, discarding the
    in-memory session-id cache every single call (still correct, since
    `_ensure_session_id` falls back to the persisted file, just wasteful).
    """
    spec = importlib.util.spec_from_file_location(
        "holdings_fetch_kite_gateway_server", _KITE_GATEWAY_SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_kite_gateway_server = _load_kite_gateway_server()

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
    },
    "required": ["workspace_root"],
}


def _holdings_count(envelope_text: str) -> int | None:
    """Best-effort count for the status message only — never used to gate
    whether the save happened; `save_tool_result` already decided that."""
    try:
        data = json.loads(envelope_text).get("data")
    except (json.JSONDecodeError, AttributeError):
        return None
    return len(data) if isinstance(data, list) else None


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

    result = await _kite_gateway_server.call_tool("get_holdings", {})
    text = result.content[0].text if result.content else ""

    if result.isError:
        # The same failure shape a raw get_holdings call already surfaces
        # today (e.g. "Please log in first using the login tool") —
        # forwarded verbatim so morning-digest's existing "no active
        # session -> fall back to cached holdings" prose keeps working
        # unchanged.
        return {
            "content": [{"type": "text", "text": f"kite_gateway.get_holdings error: {text}"}],
            "is_error": True,
        }

    saved_path = save_tool_result(_TOOL_NAME, {}, text, workspace_root)
    if saved_path is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Kite returned a result for get_holdings, but it wasn't a real, "
                        "complete tool result — not saved (see issue #24)."
                    ),
                }
            ],
            "is_error": True,
        }

    count = _holdings_count(text)
    count_text = f"{count} holdings" if count is not None else "holdings (count unavailable)"
    return {"content": [{"type": "text", "text": f"wrote {saved_path.name} — {count_text}"}]}


def build_fetch_holdings_tool() -> SdkMcpTool[Any]:
    return tool(
        "fetch_holdings",
        "Fetch the connected Zerodha account's holdings and save them to the "
        "workspace — the only way to get holdings data; kite_gateway.get_holdings "
        "itself is blocked (see issue #46: a full account's holdings can exceed "
        "the size a raw tool result can carry). Call this instead, wherever a "
        "skill or an ad hoc question previously called get_holdings directly. "
        "Returns only a short status (file written, holdings count), never the "
        "holdings themselves — read data/holdings_<date>.json (via Read, or a "
        "deterministic script like run_health_check) for the actual data.",
        _INPUT_SCHEMA,
    )(_handler)


def build_fetch_holdings_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="fetch_holdings", tools=[build_fetch_holdings_tool()])


__all__ = ["build_fetch_holdings_server", "build_fetch_holdings_tool"]
