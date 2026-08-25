"""Preflight Zerodha-connection status line for `minty`'s terminal
entrypoint (engine/interactive.py) — the Kite counterpart to
engine/claude_login.py's Claude-connection check.

Fully deterministic: no MCP call, no model turn. Checks two local files —
`data/account_identity.json` (written once, deterministically, the first
time `kite_gateway.get_profile` succeeds — see `engine/tool_capture.py`'s
docstring for why this is write-once, engine-enforced, and not a tool the
model can call to change it) and the workspace's newest
`data/holdings_*.json` (written automatically from `kite_gateway.get_holdings`)
— and prints one line before the REPL's own "Minty — connected." banner,
mirroring `ensure_logged_in()`'s "check before printing anything" shape.

Deliberately doesn't claim the Kite session is still live — Kite forces a
daily re-login, so nothing short of a real API call could know that, and
this module makes none. It states a dated fact ("found," "last refreshed
N days ago") instead, which stays true regardless of whether the
underlying session has since expired. See docs/next-phase-plan.md §5.1 for
the full design and the one state this binary check doesn't cleanly cover
(an identity anchor with no holdings file yet — falls through to the
"not connected" line, since the practical next action is the same either
way).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.tool_capture import ACCOUNT_IDENTITY_FILE

_IST = ZoneInfo("Asia/Kolkata")

_NOT_CONNECTED_LINE = (
    'Zerodha not connected yet — ask something like "what are my holdings" '
    "anytime to connect, or skip for now and you'll be prompted when you need it."
)


def _newest_holdings_date(workspace_root: Path) -> date | None:
    """The date embedded in the newest `holdings_<YYYY-MM-DD>.json` filename
    under `workspace_root/data/` — not file mtime, which a git operation or
    a file copy can reset silently. None if no holdings snapshot exists, or
    the newest filename's date doesn't parse."""
    matches = sorted(workspace_root.glob("data/holdings_*.json"))
    if not matches:
        return None
    stem = matches[-1].stem  # "holdings_2026-08-19"
    date_str = stem.removeprefix("holdings_")
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def anchor_user_id() -> str | None:
    """None if the file is missing, corrupt, or doesn't have the expected
    shape — treated the same as "no identity yet", not an error.

    `envelope["data"]` isn't reliably a flat dict: it's `structuredContent`
    when Kite's upstream response populates that field, but falls back to
    a raw list of MCP content blocks when it doesn't (see
    `mcp/kite_gateway/server.py`'s `call_tool`) — live-observed 2026-08-20
    against a real `get_profile` call to take the list-of-blocks shape, not
    the flat dict this originally assumed, which left every real "already
    connected" user stuck on the "not connected" line (see issue #5/#7).
    Handles both.

    Public (not `_`-prefixed) so `engine/kite_identity.py`'s mismatch
    check (issue #19) can reuse this exact anchor-reading logic instead of
    duplicating it — the only caller inside this module is
    `kite_connection_status_line` below."""
    try:
        envelope = json.loads(ACCOUNT_IDENTITY_FILE.read_text())
        data = envelope["data"]
        if isinstance(data, list):
            text = next(
                (block.get("text") for block in data if isinstance(block, dict) and block.get("type") == "text"),
                None,
            )
            if text is None:
                return None
            data = json.loads(text)
        return str(data["user_id"])
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        # ValueError, not just json.JSONDecodeError: `read_text()` on a file
        # truncated mid-write (tool_capture.py's write is non-atomic) can
        # raise UnicodeDecodeError before json.loads ever runs — both it and
        # JSONDecodeError are ValueError subclasses, so this catches both
        # without listing them separately.
        return None


def _days_ago_phrase(as_of: date) -> str:
    days = (datetime.now(_IST).date() - as_of).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def kite_connection_status_line(workspace_root: Path) -> str:
    """One line to print immediately after the Claude-login confirmation,
    before the REPL banner — never blocks anything, both branches just
    print and fall through to the normal prompt."""
    user_id = anchor_user_id()
    holdings_date = _newest_holdings_date(workspace_root)
    if user_id is None or holdings_date is None:
        return _NOT_CONNECTED_LINE
    return f"Holdings for account {user_id} found — last refreshed {_days_ago_phrase(holdings_date)}."


__all__ = ["kite_connection_status_line"]
