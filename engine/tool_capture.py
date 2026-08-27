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

`kite_gateway.get_profile` gets one deliberately different treatment,
below: write-once, not overwrite-every-call like everything else here. The
Zerodha account identity anchor (`data/account_identity.json`) exists to
catch a *different* account silently getting connected later — so once
it's set, no later `get_profile` call may touch it again, including
morning-digest's own step 0 (which calls `get_profile` purely to check
Kite reachability, earlier in the same turn than step 3's actual identity
comparison). An earlier version auto-captured `get_profile` the ordinary
overwrite-every-call way and that step-0 ping silently clobbered the
anchor before step 3 ever compared against it — found in review,
2026-08-20. A second version fixed that with a model-callable
`update_account_identity` tool instead, gated by a "only call this when
it's safe" instruction — rejected before it shipped: a tool that can
rewrite the one file meant to catch Minty trusting the wrong account is
exactly the kind of capability that shouldn't depend on the model
choosing correctly every time. This — a fixed, install-wide path that
silently no-ops once the file exists — is enforced in code, not prose,
and there is no tool call, from any skill, that can ever change an
existing anchor. Actually switching accounts is a deliberate, out-of-band
action: delete `data/account_identity.json` yourself, and the next
successful `get_profile` call establishes a fresh one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from engine.workspace import REPO_ROOT

_IST = ZoneInfo("Asia/Kolkata")

# Install-wide, not workspace content — see this module's own docstring
# for why get_profile is write-once here instead of living in CAPTURE_SPECS
# below with everything else.
ACCOUNT_IDENTITY_FILE = REPO_ROOT / "data" / "account_identity.json"


def today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


_today = today_ist


def _symbol(args: dict[str, Any], key: str = "symbol") -> str:
    return str(args[key]).strip().upper()


def _filing_document_filename(args: dict[str, Any], today: str) -> str:
    """Keyed by the fetched URL's own basename (e.g. the NSE-assigned PDF filename), not a symbol —
    `get_filing_document` (issue #25) only takes a URL, not a ticker."""
    url = str(args["url"])
    basename = url.rstrip("/").rsplit("/", 1)[-1] or "document"
    return f"filing_document_{basename}_{today}.json"


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
    (
        "india_screener",
        "get_fundamentals",
    ): lambda args, today: f"fundamentals_screener_{_symbol(args)}_{today}.json",
    ("india_price", "get_daily_ohlcv"): lambda args, today: f"{_symbol(args)}_ohlcv_1y.json",
    ("india_filings", "get_fii_dii_flows"): lambda args, today: f"fii_dii_{today}.json",
    ("india_filings", "get_filing_document"): _filing_document_filename,
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
    """None if `tool_name` isn't a captured tool, or a required arg is missing from `tool_input`.

    `get_profile` is special-cased ahead of `CAPTURE_SPECS`: write-once,
    install-wide, ignoring `workspace_root` entirely. None once
    `ACCOUNT_IDENTITY_FILE` already exists — the only enforcement this
    anchor gets, and it's a plain filesystem check, not a model decision.
    """
    parsed = parse_mcp_tool_name(tool_name)
    if parsed is None:
        return None
    if parsed == ("kite_gateway", "get_profile"):
        return None if ACCOUNT_IDENTITY_FILE.exists() else ACCOUNT_IDENTITY_FILE
    filename_fn = CAPTURE_SPECS.get(parsed)
    if filename_fn is None:
        return None
    try:
        filename = filename_fn(tool_input, _today())
    except (KeyError, TypeError):
        return None
    return workspace_root / "data" / filename


def _is_untrustworthy_capture(result_text: str) -> bool:
    """True when `result_text` must never be written to a captured path.
    Two distinct failure shapes, both real, found live:

    1. The {"source","as_of","data"} envelope shape every Layer-2 tool uses
       to report an application-level failure (NSE timeout, thin small-cap
       coverage) — a *successful* MCP call whose `data` field is itself
       {"error": "..."}. Every skill script's own `_envelope_data`-style
       check (e.g. red_flag_check.py) already treats this shape as
       "missing, skip this check" — never a reason to keep it, let alone
       let it overwrite a real capture. Found live 2026-08-18.
    2. Anything that isn't valid JSON matching that basic envelope contract
       at all — e.g. the Claude Agent SDK's own plain-text "exceeds maximum
       allowed tokens" redirect, substituted in place of a real tool result
       when it's too large for the SDK to pass through. That redirect
       arrives as an ordinary, non-error ToolResultBlock (nothing upstream
       flags it), so before this check existed it got written verbatim to
       the exact canonical filename a real capture would use — see issue
       #24, found live 2026-08-27 (an oversized ASM surveillance list) and
       again 2026-08-28 in the same shape.

    Genuinely malformed/unexpected content is treated the same as an
    outright fetch error: rejected, not saved — a missing capture is an
    honest, visible gap; a corrupted one silently masquerading as real data
    at its expected path is not.
    """
    try:
        parsed = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return True
    if not isinstance(parsed, dict) or not {"source", "as_of", "data"} <= parsed.keys():
        return True
    data = parsed["data"]
    return isinstance(data, dict) and "error" in data


def save_tool_result(
    tool_name: str, tool_input: dict[str, Any], result_text: str, workspace_root: Path
) -> Path | None:
    """Writes `result_text` (the tool's own raw JSON text, unparsed) to its
    captured path, creating `data/` if needed. Returns the path written, or
    None if this tool isn't captured, or if the result is untrustworthy
    (see `_is_untrustworthy_capture`) — skipped rather than saved, so it
    can't silently clobber an earlier successful capture at the same path,
    or masquerade as one that was never actually written. A rejection
    prints a `[capture]` diagnostic line (same audit-visible-but-non-
    blocking spirit as `engine/tool_budget.py`'s `[budget] ...` lines) —
    every `minty` session's stdout already lands in
    `workspace/sessions/<timestamp>.md` (engine/session_transcript.py), so
    this is durable without needing its own logging setup (see issue #26
    for the broader gap: no leveled logging exists in this codebase yet).

    Otherwise overwrites on repeat calls — freshest *successful* result
    wins, matching a retried or re-fetched call always meaning "trust this
    one," never a reason to keep stale data around. Found live 2026-08-18:
    a market-wide file (`surveillance_asm_<date>.json`, shared across every
    symbol called that day) got clobbered by a later call's error stub —
    `block.is_error` in claude_agent_sdk.py's `ClaudeSession.send()` only catches
    SDK/MCP-protocol-level failures, not this data-level shape, so the
    stub sailed straight through as an ordinary "successful" save.
    """
    path = capture_path(tool_name, tool_input, workspace_root)
    if path is None:
        return None
    if _is_untrustworthy_capture(result_text):
        print(f"[capture] rejected {tool_name}'s result for {path} — not a real, complete tool result (see issue #24)")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_text)
    return path


__all__ = ["ACCOUNT_IDENTITY_FILE", "capture_path", "parse_mcp_tool_name", "save_tool_result", "today_ist"]
