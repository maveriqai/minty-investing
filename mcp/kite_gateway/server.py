"""Minty kite_gateway MCP server (Phase 1B step 1, mcp/kite_gateway/).

Sits between any MCP client (Claude Code today, the future Minty engine)
and Zerodha's own Kite MCP server (mcp.kite.trade) — a thin pass-through,
not reimplemented broker logic (CLAUDE.md's Layer 1 definition). Ships as
option (a) from docs/phase1b-engine-design.md's Transport consequence
section: stdio-per-session, matching the other four Layer 2 servers'
`.mcp.json` shape.

**Auth model — verified live 2026-07-24, corrected from an earlier wrong
assumption:** mcp.kite.trade does *not* use MCP-transport OAuth (no 401
challenge, no dynamic client registration/PKCE) — `initialize` and
`tools/list` both succeed fully unauthenticated. Auth is entirely
session-scoped via the `login` tool itself: calling any data tool before
login returns `{"isError": true, "text": "Please log in first using the
login tool"}`; calling `login` returns a clickable
`https://mcp.kite.trade/authorize?session_id=...` URL tied to this
process's `Mcp-Session-Id`, the same flow Claude Code's own `/mcp` panel
already drives interactively. So the gateway connects to Kite
unauthenticated (no `auth=` on the client) and simply proxies `login`
through like any other tool — the caller (a human via Claude Code today,
the engine later) clicks the URL themselves, same UX as today's
`mcp__kite__login`. An earlier draft of this file implemented a full
generic OAuth2/PKCE/dynamic-client-registration client
(`mcp.client.auth.OAuthClientProvider`) for a flow that turned out not to
exist here — caught by an actual live smoke test hanging indefinitely
against the real server, removed once curl against the raw JSON-RPC
endpoint showed the real behavior above.

Tool surface is *discovered*, not hand-typed: at connect time this proxies
whatever subset of Kite's real tool list intersects ALLOWED_TOOLS below,
forwarding Kite's own name/description/inputSchema verbatim, so the
gateway can never drift from Kite's actual per-tool argument shapes —
confirmed live: the real `tools/list` response's 22 tool names match
ALLOWED_TOOLS ∪ DENIED_TOOLS below exactly. The six order-placing tools
are excluded twice over — absent from ALLOWED_TOOLS (so list_tools never
advertises them) and rejected again in call_tool as a second, redundant
check — matching CLAUDE.md's documented defense-in-depth pattern for this
guardrail (see Non-Negotiable Product Rules and
docs/phase1b-engine-design.md).

Every call this gateway completes (success or upstream-reported failure)
is wrapped in the same {"source", "as_of", "data"} envelope every other
Layer 2 server uses (CLAUDE.md grounding rule) — source is always "kite",
as_of is capture time (Kite's own per-tool responses don't reliably carry
a timestamp field worth preferring instead). This is a new response shape
existing callers (jobs/run_digest.sh, the morning-digest skill) don't yet
unwrap — see docs/phase1b-engine-design.md's "Migration path" note.
Deliberately: `.mcp.json` keeps the existing `kite` entry running
unchanged alongside this one rather than replacing it, so today's callers
keep working exactly as they do now until they're each deliberately
migrated as a separate, later task — this server is additive on day one,
not a cutover.

Live-verified 2026-07-24 (see docs/phase1b-engine-design.md): connecting,
`initialize`, `tools/list` (22 real tools, allow/deny split confirmed
correct), the pre-login `get_holdings`/`login` error/URL shapes, and —
in a follow-up session the same day — a real completed Zerodha login
(done by a human, in their own browser, never through Claude) followed by
a real authenticated `get_holdings` call succeeding on the same session
~50s later. The full chain is proven live, not just plausible on paper.

**Cross-process session persistence — added and live-verified 2026-07-24,
same day.** A fresh gateway process (i.e. a brand new Claude Code session,
since `.mcp.json` spawns one subprocess per stdio connection) was initially
found to lose the login every time: `_Upstream._session_id` was a plain
in-memory attribute, so each new process's first call minted a brand-new
Kite session via `initialize()` regardless of any earlier login. Fixed by
persisting the session id to SESSION_ID_FILE (`data/kite_gateway_session_id.json`,
already git-ignored — see CLAUDE.md's data/ convention) the moment it's
minted, and having `_ensure_session_id()` read that file first before ever
calling `initialize()`. This works because of the same fact already
verified above: resending `Mcp-Session-Id` on a *fresh connection* resumes
Kite's existing (and, once logged in, authenticated) session — that's true
whether the fresh connection comes from the same process or a different
one, since Kite holds the session server-side, keyed only by the id in the
header. Live-verified end to end — but not on the first attempt: an
earlier attempt hand-reconstructed a session id by decoding the
`session_id` query parameter out of a `login` tool's returned authorize
URL and wrote that into SESSION_ID_FILE directly, which got a real `400
Bad Request` from Kite on reuse. That parameter turned out not to be the
same string as the transport-level `Mcp-Session-Id` — the real value
(captured via `get_session_id()` right after an actual `initialize()`) is
only the `kitemcp-<uuid>` prefix, without the `|<token>` suffix the login
URL appends. The 400 was a useful negative result: it disproved that
shortcut before it could ship. The real test — a fresh login, then a
brand new gateway process reusing the code's own persisted value with no
`login` call at all — succeeded immediately, returning real holdings data
and confirming a completed login now survives across sessions, not just
across calls within one process. Zerodha's forced daily re-login (a
broker-side fact, not something this gateway controls) still applies —
this doesn't create a login that never expires, it just means the
*existing* login gets reused everywhere until Kite itself invalidates it,
instead of each new session discarding it immediately.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

import anyio
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

IST = ZoneInfo("Asia/Kolkata")
KITE_MCP_URL = "https://mcp.kite.trade/mcp"

# Persists the Kite session id across separate gateway processes (one per
# Claude Code session, per .mcp.json's stdio wiring) so a completed login
# survives opening a new session instead of forcing re-login every time —
# see _Upstream's docstring for why re-sending this id on any fresh
# connection, from any process, resumes the same Kite-side session.
# data/ is already git-ignored (CLAUDE.md's data/ convention).
#
# Security note: this id is a bearer credential for Kite's *entire* MCP
# surface once logged in, including the six order-placing tools this
# gateway itself never forwards (DENIED_TOOLS below) — anyone who reads
# this file could call mcp.kite.trade directly with it, bypassing this
# gateway's filtering entirely. _write_persisted_session_id writes it
# 0600 (owner-only) for that reason; that narrows but doesn't eliminate
# the exposure — it's still fully readable by anything running as this
# same OS user (malware, another process, a backup tool that syncs data/).
SESSION_ID_FILE = Path(__file__).parent.parent.parent / "data" / "kite_gateway_session_id.json"

# Bounds how long a persisted session id is trusted before a fresh login is
# forced again, independent of file permissions — shrinks how long a leaked
# copy of SESSION_ID_FILE would stay useful. 24h is a deliberate client-side
# choice matching Zerodha's own daily-login cadence, not a verified
# server-side TTL — Kite's actual session expiry isn't published, so this
# gateway never assumes a persisted id is still valid past this window
# rather than relying on Kite to say so.
SESSION_ID_TTL = timedelta(hours=24)

# The 16 read-only tools confirmed live via ToolSearch (see
# docs/phase1b-engine-design.md's Kite Gateway section) — the gateway never
# advertises or forwards anything outside this set.
ALLOWED_TOOLS = frozenset(
    {
        "get_holdings",
        "get_positions",
        "get_quotes",
        "get_ltp",
        "get_ohlc",
        "get_historical_data",
        "get_margins",
        "get_mf_holdings",
        "get_gtts",
        "get_order_history",
        "get_order_trades",
        "get_orders",
        "get_trades",
        "get_profile",
        "search_instruments",
        "login",
    }
)

# Never registered or forwarded, even if Kite's own tool list ever includes
# one of these under these exact names — the six order-placing tools this
# whole guardrail exists to keep out (CLAUDE.md Non-Negotiable Product
# Rules). Checked twice: once by simply never appearing in ALLOWED_TOOLS,
# and again explicitly in call_tool below, so a future edit that
# accidentally adds one to ALLOWED_TOOLS still can't forward a call to it.
DENIED_TOOLS = frozenset(
    {
        "place_order",
        "modify_order",
        "cancel_order",
        "place_gtt_order",
        "modify_gtt_order",
        "delete_gtt_order",
    }
)

assert ALLOWED_TOOLS.isdisjoint(DENIED_TOOLS)


def _envelope(data: Any) -> dict[str, Any]:
    return {
        "source": "kite",
        "as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "data": data,
    }


def filter_upstream_tools(tools: list[types.Tool]) -> list[types.Tool]:
    """Keeps only tools in ALLOWED_TOOLS, dropping anything in DENIED_TOOLS twice over."""
    return [t for t in tools if t.name in ALLOWED_TOOLS and t.name not in DENIED_TOOLS]


def _read_persisted_session_id() -> str | None:
    """Best-effort: a missing, corrupt, or TTL-expired file just means "no
    session yet", not an error — the caller falls back to a fresh
    `initialize()` in every case."""
    try:
        payload = json.loads(SESSION_ID_FILE.read_text())
        session_id = payload["session_id"]
        saved_at = datetime.fromisoformat(payload["saved_at"])
    except (FileNotFoundError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if datetime.now(IST) - saved_at > SESSION_ID_TTL:
        return None
    return session_id


def _write_persisted_session_id(session_id: str) -> None:
    """Owner-only (0600): this id is a bearer credential for Kite's full MCP
    surface, including the order-placing tools this gateway itself never
    forwards — see SESSION_ID_FILE's module-level comment. `os.fchmod`
    before writing (not just the `os.open` mode, and not after the write)
    so an existing file left over from before this fix, or created with a
    looser umask, never has the freshly-written secret sitting at its old,
    looser permissions even momentarily. Also stamps `saved_at` so
    `_read_persisted_session_id` can enforce SESSION_ID_TTL.
    """
    SESSION_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"session_id": session_id, "saved_at": datetime.now(IST).isoformat()}).encode()
    fd = os.open(SESSION_ID_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, payload)
    finally:
        os.close(fd)


class _Upstream:
    """Talks to mcp.kite.trade with a fresh HTTP connection per call, not one
    connection persisted across calls — a persisted connection turned out to
    deadlock: mcp.server.lowlevel.Server dispatches each incoming request in
    its own task, and an anyio cancel scope (which is what a streamable-http
    connection's context manager owns) can't be entered in one task and
    exited or reused from another. Verified live 2026-07-24 that this is
    safe rather than costly: re-sending `Mcp-Session-Id` on a brand new
    connection resumes Kite's existing (and, once logged in, authenticated)
    session — but re-sending `initialize` does not; it always allocates a
    *new* session id regardless of what `Mcp-Session-Id` was sent. So
    `initialize` is called exactly once, on this process's first call, and
    never again — every later call opens a fresh connection carrying only
    the now-known session id, skips re-initializing, and goes straight to
    the actual request.

    `terminate_on_close=False` matters here specifically: the SDK's default
    (True) sends an explicit session-termination signal to the server every
    time a connection's `async with` block exits — fine for a client that
    opens one connection for its whole lifetime, but fatal for this
    open-fresh-per-call pattern, where the *first* call's connection would
    otherwise terminate the shared session the moment it closes, breaking
    every call after it. Caught live 2026-07-24: without this, the second
    call ever made failed with `mcp.shared.exceptions.McpError: Session
    terminated`.

    Session-id setup is guarded by a lock (double-checked: check, acquire,
    check again) so two calls arriving before any session exists can't both
    decide they need to `initialize()` — each `initialize()` mints a brand
    new Kite session regardless of what came before, so two concurrent
    first calls without this guard would silently race, and whichever set
    `self._session_id` last would orphan the other's session (e.g. a
    `login` completed on one session while `get_holdings` ends up bound to
    a different, never-logged-off one). Everything after that first
    successful `initialize()` is a plain read of an already-set value, so
    the lock only ever matters once per process.

    Session id is also persisted to SESSION_ID_FILE (see module docstring's
    "Cross-process session persistence" note) so a completed login survives
    opening a brand new gateway process, not just repeated calls within one
    — `_ensure_session_id` checks that file before ever calling
    `initialize()`. Two known limitations, not yet handled:
    - If the persisted id is ever rejected by Kite as genuinely invalid (as
      opposed to simply "not logged in yet", which is a normal, expected
      state), this doesn't auto-recover — delete SESSION_ID_FILE to force
      a fresh session.
    - The `_session_id_lock` above only guards concurrent calls *within one
      process*. If two separate gateway processes both start with no
      SESSION_ID_FILE present yet (e.g. two Claude Code sessions opened
      around the same moment), each can independently decide no session
      exists, each call `initialize()`, and each write SESSION_ID_FILE —
      last write wins, silently orphaning whichever session lost the race,
      the same failure mode the in-process lock exists to prevent, just
      not enforced across processes. Narrow in practice for a single-user
      desktop tool, but real; a cross-process lock (e.g. an flock on
      SESSION_ID_FILE) would close this if it ever matters.
    """

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._session_id_lock = anyio.Lock()

    async def _ensure_session_id(self) -> None:
        if self._session_id is not None:
            return
        async with self._session_id_lock:
            if self._session_id is not None:  # another call won the race while we waited
                return
            persisted = _read_persisted_session_id()
            if persisted is not None:
                self._session_id = persisted
                return
            async with streamablehttp_client(KITE_MCP_URL, terminate_on_close=False) as (
                read,
                write,
                get_session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session_id = get_session_id()
                    _write_persisted_session_id(self._session_id)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[ClientSession]:
        await self._ensure_session_id()
        async with streamablehttp_client(
            KITE_MCP_URL, headers={"Mcp-Session-Id": self._session_id}, terminate_on_close=False
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                yield session

    async def list_tools(self) -> list[types.Tool]:
        async with self._connect() as session:
            result = await session.list_tools()
            return result.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        async with self._connect() as session:
            return await session.call_tool(name, arguments)


upstream = _Upstream()
server = Server("kite_gateway")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    tools = await upstream.list_tools()
    return filter_upstream_tools(tools)


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    if name not in ALLOWED_TOOLS or name in DENIED_TOOLS:
        raise ValueError(f"'{name}' is not a tool this gateway proxies.")

    result = await upstream.call_tool(name, arguments)
    data = result.structuredContent if result.structuredContent is not None else [
        block.model_dump(mode="json") for block in result.content
    ]
    envelope = _envelope({"error": data} if result.isError else data)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(envelope, indent=2))],
        structuredContent=envelope,
        isError=result.isError,
    )


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="kite_gateway",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    anyio.run(_run)
