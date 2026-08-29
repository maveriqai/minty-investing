"""A typed SDK tool that deterministically answers "does the connected
Zerodha account match the one Minty has on record" — issue #48.

`engine/kite_identity.py`'s `IdentityGuardState`/hook pair (issue #19)
already computes this comparison correctly and deterministically, but
never surfaced it to the model — `portfolio-health-check`, `morning-digest`,
and `thesis-tracker`'s own `SKILL.md` steps instead told the model to
`Read` `data/account_identity.json` itself, call `kite_gateway.get_profile`,
and compare the two `user_id` values in prose. Live-verified 2026-08-29:
the model's account-mismatch narration came entirely from that prose
read-and-compare, not from any engine-surfaced signal. This tool replaces
the prose with a single deterministic call.

Same shape as `engine/holdings_fetch.py`'s `fetch_holdings`: calls a Kite
gateway tool in-process (via `engine.kite_gateway_inprocess`, shared with
that module) rather than through a real MCP round trip, and returns only a
short, structured status — a `get_profile` response is small (unlike
holdings), so the reason for going in-process here is different: it lets
this one call also update the shared `IdentityGuardState` deterministically
as a side effect, the same state `_build_identity_deny_hook` in
`engine/harnesses/claude_agent_sdk.py` reads to hard-deny gated calls, so a
mismatch found here still trips that backstop on any later
`get_holdings`/`get_positions`/`fetch_holdings` call, exactly as if the
model had called `get_profile` directly itself.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine import kite_status
from engine.kite_gateway_inprocess import get_kite_gateway_server
from engine.kite_identity import IdentityGuardState, user_id_from_get_profile_response
from engine.tool_capture import ACCOUNT_IDENTITY_FILE, save_tool_result
from engine.workspace import REPO_ROOT

_TOOL_NAME = "mcp__kite_gateway__get_profile"

_kite_gateway_server = get_kite_gateway_server()

_INPUT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _build_handler(state: IdentityGuardState):
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        anchor_existed_before = ACCOUNT_IDENTITY_FILE.exists()

        result = await _kite_gateway_server.call_tool("get_profile", {})
        text = result.content[0].text if result.content else ""

        if result.isError:
            # Same failure shape a raw get_profile call already surfaces
            # (e.g. "Please log in first using the login tool") — forwarded
            # verbatim so each skill's existing "no active session -> show
            # login flow" prose keeps working unchanged; this tool only
            # replaces the comparison step, not connectivity handling.
            return {
                "content": [{"type": "text", "text": f"kite_gateway.get_profile error: {text}"}],
                "is_error": True,
            }

        # Write-once anchor capture — the exact path capture_path() already
        # special-cases for get_profile (ignores workspace_root entirely),
        # unchanged by this tool existing.
        save_tool_result(_TOOL_NAME, {}, text, REPO_ROOT)

        # Shared with the PreToolUse/PostToolUse hooks in
        # claude_agent_sdk.py — a mismatch found here still gates later
        # get_holdings/get_positions/fetch_holdings calls in this session.
        state.record_profile_response(text)

        live_user_id = user_id_from_get_profile_response(text)
        anchor_user_id = kite_status.anchor_user_id()

        if not anchor_existed_before:
            status = "no_anchor"
        elif anchor_user_id == live_user_id:
            status = "match"
        else:
            status = "mismatch"

        payload = {
            "status": status,
            "anchor_user_id": anchor_user_id,
            "live_user_id": live_user_id,
        }
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    return _handler


def build_identity_check_tool(state: IdentityGuardState) -> SdkMcpTool[Any]:
    return tool(
        "check_identity_match",
        "Deterministically check whether the connected Zerodha account matches "
        "the one Minty has on record — call this instead of Reading "
        "data/account_identity.json and calling kite_gateway.get_profile "
        "yourself to compare. Takes no arguments. Returns "
        '{"status": "no_anchor"|"match"|"mismatch", "anchor_user_id": ..., '
        '"live_user_id": ...}. "no_anchor" and "match" both mean proceed '
        '(the former just wrote the anchor for the first time); "mismatch" '
        "means stop and report plainly — don't fetch or overwrite holdings/"
        "positions for a different account. An error result means the same "
        "thing a get_profile failure always has (e.g. no active Kite "
        "session) — handle it the same way.",
        _INPUT_SCHEMA,
    )(_build_handler(state))


def build_identity_check_server(state: IdentityGuardState) -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="identity_check", tools=[build_identity_check_tool(state)])


__all__ = ["build_identity_check_server", "build_identity_check_tool"]
