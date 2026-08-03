"""The one concrete `Harness` implementation, backed by `claude-agent-sdk`.

All Claude-Agent-SDK-specific vocabulary (`ClaudeAgentOptions`,
`ClaudeSDKClient`, `mcp_servers`, `disallowed_tools`, `HookMatcher`,
`setting_sources`) is confined to this file on purpose — nothing outside
`harnesses/` should import `claude_agent_sdk` directly, so a future second
harness never has to touch this module.

Guardrail is defense in depth, three layers total (see docs/vision.md §5
and §4): `kite_gateway` never registers the six order tools at all;
`disallowed_tools` here removes them from the model's own tool inventory;
the `PreToolUse` hook below denies them at dispatch time regardless of
inventory state, including under `bypassPermissions`. Both SDK-native
layers are derived from the same `GuardrailPolicy` object so they can't
drift from each other. This logic, and the reasoning behind
`bypassPermissions` + a deny-hook (not an allow-list) being the only
combination that actually enforces anything under headless/no-TTY use,
carries over unchanged from the old repo's proven implementation.

`open_session()` uses `bypassPermissions` too — even though a real user is
present for an interactive Session and could in principle answer approval
prompts live via a `can_use_tool` callback. Deliberately deferred: building
a real approval UI is a separate concern from proving multi-turn
conversation state works at all, and the deny-hook guardrail already has
to exist regardless of permission mode (it's what makes the six order
tools unreachable even if a future approval UI auto-approved everything
else). Revisit once an approval UX is actually wanted, not assumed
necessary now.

`run()` (single-shot) is built on top of `open_session()` rather than the
module-level `query()` function, which is how it was first written here
(mirroring the old repo's proven pattern) and how it briefly stayed until
live-testing this rebuild reproduced the exact `RuntimeError: aclose():
asynchronous generator is already running` crash that made the old repo's
unattended digest pipeline fail for five straight trading days, unfixed.
`open_session()` doesn't hit this (verified live across multiple runs), so
`run()` now reuses that same proven path instead of maintaining a second,
separately-buggy way of talking to `claude_agent_sdk`.

Also found live, fixed here: a session's first turn was missing every MCP
tool entirely if sent immediately after `connect()` — each stdio server
(`uv run python mcp/<name>/server.py`) takes a few real seconds to finish
its handshake, and nothing waited for that. `_wait_for_mcp_servers_ready`
polls `get_mcp_status()` after connecting, before the session is handed
back to a caller. Separately, `strict_mcp_config=True` was added after a
session was found live to also pick up an unrelated MCP server configured
globally on the host machine — the same class of leak the old repo found
with `skills="all"` pulling in host-level skills.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from claude_agent_sdk.types import PreToolUseHookInput

from engine.harnesses.base import EngineResult, ToolConfig

# Confirmed live against a real session-limit-adjacent RateLimitEvent in the
# old repo, but a genuine session-limit *hit* (an error_during_execution
# exception whose text says so) hasn't been observed yet. Kept as one small,
# named check so it's a single place to correct once a real hit is seen,
# rather than guessed at across the module.
_SESSION_LIMIT_MARKERS = ("session limit",)


def _is_session_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _SESSION_LIMIT_MARKERS)


def _build_deny_hook(policy):
    async def deny_order_tools(input_data: PreToolUseHookInput, tool_use_id: str | None, context):
        tool_name = input_data.get("tool_name", "")
        if policy.is_denied(tool_name):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Order execution is never permitted — see docs/vision.md §5."
                    ),
                }
            }
        return {}

    return deny_order_tools


# The Bash tool executes via a real shell (pipes/redirects/&&/backgrounding
# all work) — a prefix check alone doesn't stop a command that starts with an
# allowed prefix and then chains something else after it. Denying any of
# these characters anywhere in the command closes that gap.
_SHELL_METACHARACTERS = (";", "&", "|", "`", "$(", "\n", "<", ">")


def _build_bash_scope_hook(allowed_prefixes: tuple[str, ...]):
    """No-op (never denies) when `allowed_prefixes` is empty."""

    async def deny_out_of_scope_bash(input_data: PreToolUseHookInput, tool_use_id: str | None, context):
        if not allowed_prefixes or input_data.get("tool_name") != "Bash":
            return {}
        command = input_data.get("tool_input", {}).get("command", "")
        matches_prefix = any(command.startswith(prefix) for prefix in allowed_prefixes)
        has_metacharacter = any(ch in command for ch in _SHELL_METACHARACTERS)
        if matches_prefix and not has_metacharacter:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Bash is scoped to specific commands for this run; {command!r} doesn't match."
                ),
            }
        }

    return deny_out_of_scope_bash


def _build_options(tools: ToolConfig) -> ClaudeAgentOptions:
    server_names = list(tools.mcp_servers.keys())
    kwargs = {
        "mcp_servers": tools.mcp_servers,
        # Found live during the interactive-session smoke test: without this,
        # a session also picks up whatever MCP servers are configured
        # globally on the host machine (a personal "claude.ai Notion"
        # connector showed up unprompted) — the same class of leak the old
        # repo found with skills="all" pulling in host-level skills. This
        # scopes strictly to the mcp_servers dict passed in, nothing else.
        "strict_mcp_config": True,
        "disallowed_tools": list(tools.guardrail.denied_tool_names(server_names)),
        "hooks": {
            "PreToolUse": [
                HookMatcher(
                    matcher=None,
                    hooks=[
                        _build_deny_hook(tools.guardrail),
                        _build_bash_scope_hook(tools.allowed_bash_prefixes),
                    ],
                )
            ]
        },
        "setting_sources": ["project"],
        "skills": tools.skills,
        "permission_mode": "bypassPermissions",
    }
    if tools.builtin_tools is not None:
        kwargs["tools"] = list(tools.builtin_tools)
    if tools.max_buffer_size is not None:
        kwargs["max_buffer_size"] = tools.max_buffer_size
    return ClaudeAgentOptions(**kwargs)


_MCP_READY_TIMEOUT_S = 15.0
_MCP_READY_POLL_INTERVAL_S = 0.5


async def _wait_for_mcp_servers_ready(
    client: ClaudeSDKClient,
    expected: set[str],
    *,
    timeout_s: float = _MCP_READY_TIMEOUT_S,
    poll_interval_s: float = _MCP_READY_POLL_INTERVAL_S,
) -> None:
    """Blocks until every server in `expected` reports a non-"pending"
    status, or `timeout_s` elapses.

    Found live during the first interactive-session smoke test: a turn sent
    immediately after `connect()` was missing every MCP tool entirely — the
    model's own tool list showed india_price/kite_gateway/etc. as "still
    connecting," and either a second turn or an inserted delay saw them
    fine. Each stdio server is a fresh `uv run python ...` subprocess
    importing pandas/yfinance/etc., which takes a few real seconds to
    finish its handshake — nothing waited for that before the first
    `send()`. Polls `get_mcp_status()` rather than a blind sleep, so a
    session becomes usable as soon as it actually can be, not after a
    fixed worst-case delay every time. A server still pending at the
    timeout doesn't block the session forever — better to proceed and let
    that one tool call fail than hang a conversation indefinitely.
    """
    if not expected:
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        status = await client.get_mcp_status()
        pending = {
            s["name"]
            for s in status.get("mcpServers", [])
            if s["name"] in expected and s["status"] == "pending"
        }
        if not pending or loop.time() >= deadline:
            return
        await asyncio.sleep(poll_interval_s)


class ClaudeSession:
    """Wraps a connected `ClaudeSDKClient` — multi-turn, holds conversation
    state across calls to `send()` for as long as the session stays open.
    """

    def __init__(self, client: ClaudeSDKClient) -> None:
        self._client = client
        self.last_result: EngineResult | None = None

    async def send(self, prompt: str) -> AsyncIterator[str]:
        await self._client.query(prompt)
        async for message in self._client.receive_response():
            kind = type(message).__name__
            if kind == "AssistantMessage":
                for block in message.content:
                    if type(block).__name__ == "TextBlock":
                        yield block.text
            elif kind == "ResultMessage":
                if message.subtype == "success":
                    self.last_result = EngineResult(
                        ok=True, text=message.result, error_kind=None, raw=message
                    )
                else:
                    self.last_result = EngineResult(
                        ok=False, text=None, error_kind=message.subtype, raw=message
                    )


class ClaudeAgentSDKHarness:
    """`Harness` implementation backed by `claude_agent_sdk`."""

    async def run(self, prompt: str, tools: ToolConfig) -> EngineResult:
        """Single-shot: open a session, send one turn, close.

        Originally built on the module-level `query()` function directly
        (the old repo's proven pattern) — but live-testing this rebuild
        reproduced the exact `RuntimeError: aclose(): asynchronous
        generator is already running` crash that made the old repo's
        unattended digest pipeline fail for five straight days, unfixed.
        `open_session()` doesn't hit this (verified live, multiple runs),
        so `run()` is now a thin wrapper over the same session machinery
        instead of a second, separately-buggy code path to `claude_agent_sdk`.
        One proven path for both single-shot and multi-turn use, not two.
        """
        try:
            async with self.open_session(tools) as session:
                async for _ in session.send(prompt):
                    pass
                return session.last_result or EngineResult(
                    ok=False, text=None, error_kind="no_result", raw=None
                )
        except Exception as exc:  # noqa: BLE001 - normalized into EngineResult, not swallowed
            error_kind = "session_limit" if _is_session_limit_error(exc) else "other"
            return EngineResult(ok=False, text=None, error_kind=error_kind, raw=exc)

    @asynccontextmanager
    async def open_session(self, tools: ToolConfig):
        options = _build_options(tools)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        await _wait_for_mcp_servers_ready(client, set(tools.mcp_servers.keys()))
        session = ClaudeSession(client)
        try:
            yield session
        finally:
            await client.disconnect()
