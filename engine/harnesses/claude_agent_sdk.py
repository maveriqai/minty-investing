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

Separately, `_build_identity_record_hook`/`_build_identity_deny_hook`
(issue #19) are a second, unrelated `PostToolUse`/`PreToolUse` pair: a
deterministic backstop for the Zerodha account-identity mismatch check
that was previously pure prose in three skills' own SKILL.md steps. See
`engine/kite_identity.py`'s module docstring for the full design and its
deliberately narrow, fail-open scope.

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
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from claude_agent_sdk.types import PostToolUseHookInput, PreToolUseHookInput

from engine import skills
from engine.guardrail import tool_name_suffix
from engine.harnesses.base import EngineResult, ToolConfig
from engine.kite_identity import IDENTITY_GATED_TOOLS, IdentityGuardState
from engine.skill_tools import build_skill_tools_server
from engine.sources_footer import build_footer
from engine.staged_skill_tools import (
    STAGED_WORKFLOWS_SERVER_NAME,
    build_staged_workflow_tools_server,
)
from engine.tool_budget import TurnBudgetTracker, build_budget_tracker
from engine.tool_capture import parse_mcp_tool_name, save_tool_result, today_ist
from engine.workspace_notes import build_workspace_notes_server

_SKILL_SCRIPTS_SERVER_NAME = "skill_scripts"
_WORKSPACE_NOTES_SERVER_NAME = "workspace_notes"

# vision.md §8's own requirement: state the read-only guarantee inline, at
# the moment a user is asked to connect their account, not buried in a docs
# file. Found missing live 2026-08-17 — a real Kite login prompt showed
# only Kite's own generic "AI is unpredictable" warning, forwarded verbatim
# per kite_gateway's pass-through design (it never wraps or edits Kite's
# own tool descriptions/responses — see mcp/kite_gateway/server.py), with
# nothing from Minty itself. This fires from `system_prompt` rather than a
# skill's own SKILL.md because the login prompt can be triggered without
# any skill matching at all (an ad hoc "what are my holdings" goes straight
# through `kite_gateway.get_holdings`).
_KITE_LOGIN_SYSTEM_PROMPT = (
    "Whenever you present a Kite/Zerodha login link to the user — whether "
    "you're running a skill or just answering an ad hoc question that "
    "needs live account data — state inline, in your own words, that "
    "Minty is read-only against the connected account: order-placing and "
    "order-modifying tools are never in Minty's own tool surface at all, "
    "not just withheld by policy, regardless of what the underlying "
    "Zerodha OAuth grant technically permits. Say this at the moment you "
    "ask them to connect, not only if they ask later.\n\n"
    "Separately: if you're about to call any other kite_gateway tool ad "
    "hoc — not as part of a skill step that already calls get_profile "
    "itself (morning-digest step 3, portfolio-health-check step 2) — call "
    "kite_gateway.get_profile once first. This is what populates Minty's "
    "own account-identity anchor (data/account_identity.json); skipping "
    "it leaves the Kite connection status line reporting 'not connected' "
    "on every future session even once you have real cached data."
)

# Issue #14, piece 1 ("explicit remember"): `update_workspace_notes` is
# already registered unconditionally (below), so nothing stops the model
# calling it outside a skill step today except that every existing
# instruction to do so lives inside a specific skill's own SKILL.md (e.g.
# portfolio-health-check step 5, thesis-tracker's thesis-file step,
# morning-digest step 11) — none of which fires on a plain ad hoc chat
# turn. Same shape as the Kite-login prompt above: a behavior that has to
# work whether or not any skill matched this turn, so it belongs in
# `system_prompt`, not a skill file. Deliberately narrow — only the
# user's own explicit "remember/note/save this" triggers it; this is not
# the post-turn automatic extraction docs/next-phase-plan.md §8 also
# discusses, which is unbuilt and would need its own, much more cautious
# design (an automated judgment call risks polluting a file CLAUDE.md
# wants small and hand-curated).
_REMEMBER_SYSTEM_PROMPT = (
    "If the user explicitly asks you to remember, note, or save something "
    "for later — in any turn, whether or not a skill is running — call "
    "update_workspace_notes yourself right then, target 'notes.md' unless "
    "they're clearly talking about one specific stock's thesis (then "
    "'theses/<SYMBOL>.md'). Read the current content first if the file "
    "exists, merge your addition in, don't wait for a skill step to do "
    "this for you and don't just say you'll remember it without actually "
    "calling the tool."
)

_SYSTEM_PROMPT = f"{_KITE_LOGIN_SYSTEM_PROMPT}\n\n{_REMEMBER_SYSTEM_PROMPT}"

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


def _build_identity_record_hook(state: IdentityGuardState):
    """PostToolUse: the moment any `*__get_profile` call returns, compare
    its live `user_id` against `data/account_identity.json` and update
    `state` — see engine/kite_identity.py for why this only ever moves
    `state.mismatch` False -> True, never the reverse, and why an
    unparseable response never counts as a mismatch either way.

    Prints one `[identity]` diagnostic per unparseable response instead of
    staying silent — the parsed shape is live-confirmed (2026-08-25, see
    `engine/kite_identity.py`'s `user_id_from_get_profile_response`
    docstring), but nothing guarantees it stays that way forever, so this
    stands as an ongoing canary rather than being removed now that it's
    proven once: a future shape change would otherwise leave the whole
    mismatch check quietly inert with nothing anywhere to reveal that,
    the same audit-visible-but-non-blocking spirit as
    `engine/tool_budget.py`'s `[budget] ...` lines."""

    async def record_profile_identity(input_data: PostToolUseHookInput, tool_use_id: str | None, context):
        if tool_name_suffix(input_data.get("tool_name", "")) == "get_profile":
            parsed = state.record_profile_response(input_data.get("tool_response"))
            if not parsed:
                print(
                    "[identity] couldn't parse this get_profile response for the "
                    "account-identity check (issue #19) — the mismatch check did "
                    "not run for this call."
                )
        return {}

    return record_profile_identity


def _build_identity_deny_hook(state: IdentityGuardState):
    """PreToolUse: hard-denies `get_holdings`/`get_positions` once
    `_build_identity_record_hook` above has confirmed a real account
    mismatch this session — the engine-enforced backstop for what was
    previously only a "stop if the accounts don't match" prose
    instruction repeated in three skills' own SKILL.md steps (issue #19).
    Never denies for any other reason (see engine/kite_identity.py's
    docstring for why "no check has happened yet" deliberately isn't
    grounds for a hard deny here)."""

    async def deny_on_identity_mismatch(input_data: PreToolUseHookInput, tool_use_id: str | None, context):
        tool_name = input_data.get("tool_name", "")
        if tool_name_suffix(tool_name) not in IDENTITY_GATED_TOOLS:
            return {}
        if state.mismatch:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "A different Zerodha account is connected than the one Minty has "
                        "cached data for. Stop and tell the user plainly — don't fetch or "
                        "overwrite cached holdings/positions. Engine-enforced, not something "
                        "resolvable from inside this conversation: a human must delete "
                        "data/account_identity.json to accept the new account."
                    ),
                }
            }
        return {}

    return deny_on_identity_mismatch


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
    skill_names = tools.skills if isinstance(tools.skills, list) else []
    # A skill declaring `stages` is exposed only through its own
    # run_staged_<skill> tool (below), never through native
    # Skill-invocation too — see docs/staged-skill-execution-design.md §8's
    # first requirement. `staged_skill_names` is computed from the full
    # list so a stage's own SKILL.md-declared deterministic scripts still
    # get built into skill_scripts (unaffected) even though the skill
    # itself is filtered out of `native_skill_names` below.
    staged_skill_names = [name for name in skill_names if skills.load_stages(name)]
    native_skill_names = [name for name in skill_names if name not in staged_skill_names]

    mcp_servers = dict(tools.mcp_servers)
    skill_scripts_server = build_skill_tools_server(skill_names)
    if skill_scripts_server is not None:
        mcp_servers[_SKILL_SCRIPTS_SERVER_NAME] = skill_scripts_server
    # Unconditional, unlike skill_scripts above: every skill in every
    # workspace uses the same one notes.md convention (docs/vision.md's
    # workspace tier), so there's no per-skill declaration to gate this on.
    mcp_servers[_WORKSPACE_NOTES_SERVER_NAME] = build_workspace_notes_server()
    if tools.include_staged_tools and staged_skill_names:
        staged_workflows_server = build_staged_workflow_tools_server(staged_skill_names, tools)
        if staged_workflows_server is not None:
            mcp_servers[STAGED_WORKFLOWS_SERVER_NAME] = staged_workflows_server

    server_names = list(mcp_servers.keys())
    # One instance per `_build_options` call, i.e. per `open_session()` —
    # shared by the two hooks below via closure, so an identity check
    # earlier in a multi-turn session still gates a later turn's call, not
    # just the turn that did the checking (issue #19).
    identity_state = IdentityGuardState()
    kwargs = {
        "mcp_servers": mcp_servers,
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
                        _build_identity_deny_hook(identity_state),
                    ],
                )
            ],
            "PostToolUse": [
                HookMatcher(matcher=None, hooks=[_build_identity_record_hook(identity_state)])
            ],
        },
        "setting_sources": ["project"],
        "skills": native_skill_names if isinstance(tools.skills, list) else tools.skills,
        "permission_mode": "bypassPermissions",
        "system_prompt": _SYSTEM_PROMPT,
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


def _tool_result_text(content: Any) -> str | None:
    """A `ToolResultBlock.content` is `str | list[dict] | None` — flattens the
    list-of-content-blocks shape (`[{"type": "text", "text": "..."}]`) down
    to the same plain text a `str` content already is. None if there's no
    text content to capture (e.g. an image-only or empty result).

    Joins *all* matching text blocks, unlike the similarly-shaped filters in
    `engine/kite_identity.py` and `engine/kite_status.py` (which take only
    the first block) — this one is archiving arbitrary tool output that
    could legitimately span multiple blocks, not extracting a single JSON
    envelope. Deliberate divergence, not drift — see issue #20."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return "".join(parts) if parts else None


class ClaudeSession:
    """Wraps a connected `ClaudeSDKClient` — multi-turn, holds conversation
    state across calls to `send()` for as long as the session stays open.
    """

    def __init__(self, client: ClaudeSDKClient, budget_tracker: TurnBudgetTracker | None = None) -> None:
        self._client = client
        self._budget_tracker = budget_tracker if budget_tracker is not None else TurnBudgetTracker({})
        self.last_result: EngineResult | None = None
        self.last_captures: list[tuple[str, str, Path]] = []
        self.last_over_budget: list[str] = []

    async def send(self, prompt: str, *, workspace_root: Path | None = None) -> AsyncIterator[str]:
        """`workspace_root`, when given, turns on auto-capture: every Layer-2
        MCP tool result this turn produces is saved to the workspace's
        `data/` under the same filename its skill's own SKILL.md already
        documents (see engine/tool_capture.py) — the model no longer has to
        remember to save it there itself.

        Also mechanically appends a Sources footer + the SEBI disclaimer
        (see engine/sources_footer.py) once the turn's own text is fully
        streamed, if `workspace_root` is set and this turn captured at
        least one file — docs/vision.md §5 requires both on every grounded
        output, and live-testing found the model reliably didn't write
        either on its own (the same class of dropped-closing-step failure
        `update_workspace_notes` fixed for notes.md). A turn that captured
        nothing (plain chat, a workspace-less turn) gets no footer — see
        `build_footer`'s own docstring.

        Resets this session's per-turn tool-call counter (see
        engine/tool_budget.py) before sending — a skill's declared call
        expectation (e.g. morning-digest's india_news.get_news count)
        applies per turn, not cumulatively across a whole session. Never
        blocks a call; `last_over_budget` after the turn just lists which
        budgeted tools, if any, ran over — an audit signal, not
        enforcement (see engine/tool_budget.py's docstring for why).

        A `run_staged_<skill>` call (see engine/staged_skill_tools.py) gets
        special handling: its own returned text already *is* the finished,
        fully-composed result — `engine/staged_skills.py`'s
        `compose_and_save` built it from every tool call across all four
        stage sessions, none of which this session ever saw directly. Once
        that result lands, this method stops yielding the model's own
        subsequent text (its paraphrase of that same result, minus the
        footer — models don't reliably echo trailing boilerplate) and
        yields the staged tool's own text instead, skipping this session's
        own `captures`-based footer entirely. That footer would otherwise
        still fire (this session's `captures` is never empty — it always
        has at least morning-digest's own step-0 `get_profile` call) and
        silently overwrite a correct, multi-source footer with one citing
        only the one call this particular session happened to make itself
        — found live 2026-08-20, see issue #15.
        """
        self._budget_tracker.reset()
        await self._client.query(prompt)
        pending_tool_calls: dict[str, tuple[str, dict[str, Any]]] = {}
        captures: list[tuple[str, str, Path]] = []
        staged_output: str | None = None
        async for message in self._client.receive_response():
            kind = type(message).__name__
            if kind == "AssistantMessage":
                for block in message.content:
                    block_kind = type(block).__name__
                    if block_kind == "TextBlock":
                        if staged_output is None:
                            yield block.text
                    elif block_kind == "ToolUseBlock":
                        pending_tool_calls[block.id] = (block.name, block.input)
                        self._budget_tracker.record(block.name)
            elif kind == "UserMessage":
                for block in getattr(message, "content", None) or []:
                    if type(block).__name__ != "ToolResultBlock" or block.is_error:
                        continue
                    call = pending_tool_calls.get(block.tool_use_id)
                    if call is None:
                        continue
                    tool_name, tool_input = call
                    parsed = parse_mcp_tool_name(tool_name)
                    if parsed is not None and parsed[0] == STAGED_WORKFLOWS_SERVER_NAME:
                        text = _tool_result_text(block.content)
                        if text is not None:
                            staged_output = text
                            yield text
                        continue
                    if workspace_root is None:
                        continue
                    text = _tool_result_text(block.content)
                    if text is None:
                        continue
                    saved_path = save_tool_result(tool_name, tool_input, text, workspace_root)
                    if saved_path is None:
                        continue
                    if parsed is not None:
                        captures.append((parsed[0], parsed[1], saved_path))
            elif kind == "ResultMessage":
                if message.subtype == "success":
                    self.last_result = EngineResult(
                        ok=True, text=message.result, error_kind=None, raw=message
                    )
                else:
                    self.last_result = EngineResult(
                        ok=False, text=None, error_kind=message.subtype, raw=message
                    )

        self.last_captures = captures
        self.last_over_budget = self._budget_tracker.over_budget()
        if staged_output is None and workspace_root is not None and captures:
            footer = build_footer(captures, as_of=today_ist(), workspace_root=workspace_root)
            if footer:
                yield footer


class ClaudeAgentSDKHarness:
    """`Harness` implementation backed by `claude_agent_sdk`."""

    async def run(
        self, prompt: str, tools: ToolConfig, *, workspace_root: Path | None = None
    ) -> EngineResult:
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

        `workspace_root` is threaded straight to the underlying
        `session.send()` — without it, this entire single-shot path had no
        auto-capture, no Sources footer, and no SEBI disclaimer, silently
        (found live 2026-08-08: a non-staged skill run through
        `engine/run.py` fell back to the model saving files itself, under
        made-up names, with no footer or disclaimer at all).

        Chunks are accumulated here rather than discarded, and used to
        build the returned text when the turn succeeds — `session.
        last_result.text` alone is the SDK's own raw final message and
        does *not* include the footer, since `send()` appends it as one
        more streamed chunk after that result is already set (see
        `ClaudeSession.send`'s own docstring). Accumulating chunks is what
        `engine/interactive.py`'s `_run_turn` already does for the same
        reason.
        """
        try:
            async with self.open_session(tools) as session:
                chunks: list[str] = []
                async for chunk in session.send(prompt, workspace_root=workspace_root):
                    chunks.append(chunk)
                for line in session.last_over_budget:
                    print(f"[budget] {line}")
                result = session.last_result
                if result is None:
                    return EngineResult(ok=False, text=None, error_kind="no_result", raw=None)
                if not result.ok:
                    return result
                return EngineResult(ok=True, text="".join(chunks), error_kind=None, raw=result.raw)
        except Exception as exc:  # noqa: BLE001 - normalized into EngineResult, not swallowed
            error_kind = "session_limit" if _is_session_limit_error(exc) else "other"
            return EngineResult(ok=False, text=None, error_kind=error_kind, raw=exc)

    @asynccontextmanager
    async def open_session(self, tools: ToolConfig):
        options = _build_options(tools)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        await _wait_for_mcp_servers_ready(client, set(options.mcp_servers.keys()))
        skill_names = tools.skills if isinstance(tools.skills, list) else []
        session = ClaudeSession(client, build_budget_tracker(skill_names))
        try:
            yield session
        finally:
            await client.disconnect()
