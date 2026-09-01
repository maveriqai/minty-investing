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
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from claude_agent_sdk.types import PostToolUseHookInput, PreToolUseHookInput

from engine import skills
from engine.guardrail import tool_name_suffix
from engine.harnesses.base import EngineResult, ToolConfig
from engine.holding_lookup import build_holding_lookup_server
from engine.holdings_fetch import build_fetch_holdings_server
from engine.identity_check import build_identity_check_server
from engine.kite_identity import IDENTITY_GATED_TOOLS, IdentityGuardState
from engine.memory_candidates import build_memory_candidate_server
from engine.skill_tools import build_skill_tools_server
from engine.sources_footer import DISCLAIMER, build_footer
from engine.staged_skill_tools import (
    STAGED_WORKFLOWS_SERVER_NAME,
    build_staged_workflow_tools_server,
)
from engine.time_ist import today_ist
from engine.tool_audit import append_tool_calls, new_audit_log_path
from engine.tool_budget import TurnBudgetTracker, build_budget_tracker
from engine.tool_capture import parse_mcp_tool_name, save_tool_result
from engine.workspace import is_within_known_workspace_roots
from engine.workspace_notes import build_workspace_notes_server

_SKILL_SCRIPTS_SERVER_NAME = "skill_scripts"
_WORKSPACE_NOTES_SERVER_NAME = "workspace_notes"
_MEMORY_CANDIDATES_SERVER_NAME = "memory_candidates"
_FETCH_HOLDINGS_SERVER_NAME = "fetch_holdings"
_HOLDING_LOOKUP_SERVER_NAME = "holding_lookup"
_IDENTITY_CHECK_SERVER_NAME = "identity_check"

# Blocked unconditionally, everywhere — not via GuardrailPolicy (that's
# scoped to the no-order-execution guarantee only): a full account's
# get_holdings result can exceed the size a raw tool result can carry
# (issue #46), silently dropping the whole call. fetch_holdings
# (engine/holdings_fetch.py) is the only path to holdings data now; it
# reuses kite_gateway's own get_holdings under the hood, in-process, so
# Layer 1 itself is unchanged and still a faithful, complete proxy.
_ALWAYS_DISALLOWED_TOOLS = ("mcp__kite_gateway__get_holdings",)

# Read/Glob are the model's own direct, unmediated filesystem access —
# under bypassPermissions, nothing else stopped a call reading anywhere the
# process can see (issue #55; Glob was added to builtin_tools after the
# issue was filed for research-discovery's workspace-check step, but has
# the identical exposure). Scoped to the workspace roots specifically
# (`is_within_known_workspace_roots` — workspace/ + the dev-only
# .dev-workspaces/ sandbox), not the whole repo tree: REPO_ROOT/data/ holds
# the live Kite session token (kite_gateway_session_id.json) and the
# account-identity anchor (account_identity.json), both deliberately kept
# outside workspace/ per CLAUDE.md, and a repo-root-wide boundary would
# still let Read pull the session token directly — mcp/kite_gateway/
# server.py's own comment warns that file "could call mcp.kite.trade
# directly with it, bypassing" the read-only gateway entirely. Every real
# Read/Glob call site in every skill's SKILL.md already resolves against
# the workspace root the engine hands the model at turn start
# (augment_prompt_with_workspace's "[Active workspace: ...]" prefix), never
# repo-root data/results/engine/. Write isn't here — issue #55 found zero
# legitimate use of it anywhere, so it's removed from builtin_tools
# entirely (engine/config.py) rather than scoped.
_WORKSPACE_SCOPED_TOOLS = {"Read": "file_path", "Glob": "path"}

# vision.md §8's own requirement: state the read-only guarantee inline, at
# the moment a user is asked to connect their account, not buried in a docs
# file. Found missing live 2026-08-17 — a real Kite login prompt showed
# only Kite's own generic "AI is unpredictable" warning, forwarded verbatim
# per kite_gateway's pass-through design (it never wraps or edits Kite's
# own tool descriptions/responses — see mcp/kite_gateway/server.py), with
# nothing from Minty itself. This fires from `system_prompt` rather than a
# skill's own SKILL.md because the login prompt can be triggered without
# any skill matching at all (an ad hoc "what are my holdings" goes straight
# through `fetch_holdings` — see engine/holdings_fetch.py, issue #46).
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
    "hoc — not as part of a skill step that already calls "
    "check_identity_match itself (morning-digest, portfolio-health-check, "
    "thesis-tracker) — call check_identity_match once first. This is what "
    "populates Minty's own account-identity anchor "
    "(data/account_identity.json); skipping it leaves the Kite connection "
    "status line reporting 'not connected' on every future session even "
    "once you have real cached data."
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
# user's own explicit "remember/note/save this" triggers it. The lower-
# confidence sibling case — something durable surfaces without the user
# framing it that way — is _MEMORY_CANDIDATE_SYSTEM_PROMPT below, which
# deliberately does NOT write notes.md directly (see
# engine/memory_candidates.py's module docstring for why that's kept to a
# staged, human-reviewed queue instead).
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

# Issue #14, piece 2. Separate tool, separate instruction from the one
# above on purpose: this is an uncertain judgment call (was this actually
# durable, or just this turn's context?), so it's routed to a staging
# file via `stage_memory_candidate`, never straight to notes.md — the
# session-start review (engine/interactive.py's `_repl`) is the only path
# from there into `update_workspace_notes`. Written as a plain-text
# instruction rather than a deterministic engine-side check because
# there's no deterministic way to tell "durable preference" from "one-off
# context" — that judgment has to happen somewhere, and it belongs to the
# model that just had the actual conversation, not a keyword heuristic.
_MEMORY_CANDIDATE_SYSTEM_PROMPT = (
    "Separately: if something durable came up this turn that the user did "
    "NOT explicitly ask you to remember — a preference mentioned in "
    "passing, an open thread, a decision worth tracking — call "
    "stage_memory_candidate with a one-line draft and a short note on what "
    "grounds it. Use your judgment about what counts as durable: skip "
    "one-off, point-in-time content (a price, a single day's number, "
    "anything that'll be stale next turn) — same rule notes.md itself "
    "follows. When genuinely unsure whether something is durable, stage "
    "it anyway; a person reviews every staged candidate before anything "
    "reaches notes.md, so the cost of staging something that turns out "
    "not to matter is low. Don't stage the same thing update_workspace_notes "
    "already saved this turn."
)

# Issue #39: a skill's closing follow-up question (e.g. screen-indian-
# stocks's "want me to go deeper on any one name?") was emergent model
# behavior folded into flowing prose, immediately before a Sources footer
# that can itself run long (#36) — live onboarding feedback found it easy
# to miss entirely. No shared "close with a question" convention existed
# in any skill's own SKILL.md to build on (checked: none declare one), so
# this is one centralized instruction, alongside the three above, rather
# than editing every skill file. `engine/interactive.py`'s `_run_turn`
# looks for the exact `Next:`-prefixed last line this asks for and
# displays it separately, after the footer — see that module.
_NEXT_STEP_SYSTEM_PROMPT = (
    "When your reply ends with a follow-up question or suggested next "
    "action for the user, put that — and only that — on its own final "
    "line, prefixed with exactly \"Next: \" (nothing else before it on "
    "the line). The engine displays this separately from the rest of "
    "your reply; don't also restate the same question earlier in your "
    "prose."
)

# Issue #54: none of the four prompts above state what Minty *is* — they
# each govern one specific behavior (Kite disclosure, remember, memory
# staging, Next: formatting) but none says "you are an investing-research
# tool" at all. Skill descriptions constrain which *skill* fires, but a
# message that matches no skill (a plain "write me a poem") never touches
# that scoping — it falls straight through to generic Claude conversation.
# The structural containment elsewhere in this engine (six finance-only MCP
# servers in .mcp.json, builtin_tools trimmed to Read/Glob/Skill in
# engine/config.py, no Bash/WebFetch/WebSearch) only bounds *actions*; it
# does nothing for off-topic *prose*, since answering a trivia question
# needs no tool call. Same prompt-only-guarantee category as the rest of
# this file and as issue #23's memory-pipeline gate — there's no
# deterministic way to enforce "stay on topic" at the engine level, so this
# is an instruction, not a check.
_TOPIC_SCOPE_SYSTEM_PROMPT = (
    "You are Minty, a local investment-research and portfolio-monitoring "
    "tool for Indian retail equity investors, running against this user's "
    "own connected Zerodha account. You are not a general-purpose "
    "assistant. If the user asks something with no connection to investing "
    "research, their portfolio, or Indian markets — write code unrelated "
    "to this project, general trivia, creative writing, and the like — "
    "say briefly that this is outside what Minty does and redirect them "
    "back to investing research, rather than answering it as a generic "
    "assistant would."
)

_SYSTEM_PROMPT = (
    f"{_TOPIC_SCOPE_SYSTEM_PROMPT}\n\n{_KITE_LOGIN_SYSTEM_PROMPT}\n\n{_REMEMBER_SYSTEM_PROMPT}"
    f"\n\n{_MEMORY_CANDIDATE_SYSTEM_PROMPT}\n\n{_NEXT_STEP_SYSTEM_PROMPT}"
)

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


async def _deny_outside_workspace(input_data: PreToolUseHookInput, tool_use_id: str | None, context):
    """PreToolUse: denies `Read`/`Glob` calls whose resolved path falls
    outside the workspace roots — see `_WORKSPACE_SCOPED_TOOLS`'s own
    comment for why this boundary (not the whole repo tree) and why Write
    isn't handled here at all (issue #55).

    No "path omitted" carve-out for Glob (its `path` arg is optional,
    defaulting to cwd/REPO_ROOT): every real Glob call in the skills
    explicitly sets `path` to somewhere in the active workspace, so an
    omitted path is never legitimately exercised — resolving it to cwd and
    denying (cwd is outside the workspace roots) is simpler than special-
    casing it open. A plain function, not a `_build_*_hook` closure, unlike
    its neighbors above: it closes over nothing that varies per call or
    session, so a builder here would only exist to look consistent."""
    tool_name = input_data.get("tool_name", "")
    arg_name = _WORKSPACE_SCOPED_TOOLS.get(tool_name)
    if arg_name is None:
        return {}
    raw_path = input_data.get("tool_input", {}).get(arg_name, "")
    try:
        resolved = Path(raw_path).resolve()
    except OSError:
        resolved = None
    if resolved is not None and is_within_known_workspace_roots(resolved):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{tool_name} is scoped to the active workspace; {raw_path!r} "
                "resolves outside it (issue #55)."
            ),
        }
    }


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

    # One instance per `_build_options` call, i.e. per `open_session()` —
    # shared by the two hooks below and by check_identity_match (issue #48)
    # via closure, so an identity check earlier in a multi-turn session
    # still gates a later turn's call, not just the turn that did the
    # checking (issue #19).
    identity_state = IdentityGuardState()

    mcp_servers = dict(tools.mcp_servers)
    skill_scripts_server = build_skill_tools_server(skill_names)
    if skill_scripts_server is not None:
        mcp_servers[_SKILL_SCRIPTS_SERVER_NAME] = skill_scripts_server
    # Unconditional, unlike skill_scripts above: every skill in every
    # workspace uses the same one notes.md convention (docs/vision.md's
    # workspace tier), so there's no per-skill declaration to gate this on.
    mcp_servers[_WORKSPACE_NOTES_SERVER_NAME] = build_workspace_notes_server()
    # Same unconditional treatment, same reason — issue #14 piece 2.
    mcp_servers[_MEMORY_CANDIDATES_SERVER_NAME] = build_memory_candidate_server()
    # Same unconditional treatment — every session needs the safe holdings
    # path available, since kite_gateway's own get_holdings is disallowed
    # below (issue #46).
    mcp_servers[_FETCH_HOLDINGS_SERVER_NAME] = build_fetch_holdings_server()
    # Same unconditional treatment — the single-symbol lookup this backs
    # (get_holding_for_symbol) is how thesis-tracker reads one holding out
    # of the cache fetch_holdings just wrote, instead of Reading the whole
    # file itself or calling the now-blocked get_holdings (issue #50).
    mcp_servers[_HOLDING_LOOKUP_SERVER_NAME] = build_holding_lookup_server()
    # Same unconditional treatment — every session needs the deterministic
    # identity-match check available, replacing the prose Read-and-compare
    # steps portfolio-health-check/morning-digest/thesis-tracker used to do
    # themselves (issue #48).
    mcp_servers[_IDENTITY_CHECK_SERVER_NAME] = build_identity_check_server(identity_state)
    if tools.include_staged_tools and staged_skill_names:
        staged_workflows_server = build_staged_workflow_tools_server(staged_skill_names, tools)
        if staged_workflows_server is not None:
            mcp_servers[STAGED_WORKFLOWS_SERVER_NAME] = staged_workflows_server

    server_names = list(mcp_servers.keys())
    kwargs = {
        "mcp_servers": mcp_servers,
        # Found live during the interactive-session smoke test: without this,
        # a session also picks up whatever MCP servers are configured
        # globally on the host machine (a personal "claude.ai Notion"
        # connector showed up unprompted) — the same class of leak the old
        # repo found with skills="all" pulling in host-level skills. This
        # scopes strictly to the mcp_servers dict passed in, nothing else.
        "strict_mcp_config": True,
        "disallowed_tools": [
            *tools.guardrail.denied_tool_names(server_names),
            *_ALWAYS_DISALLOWED_TOOLS,
        ],
        "hooks": {
            "PreToolUse": [
                HookMatcher(
                    matcher=None,
                    hooks=[
                        _build_deny_hook(tools.guardrail),
                        _build_bash_scope_hook(tools.allowed_bash_prefixes),
                        _build_identity_deny_hook(identity_state),
                        _deny_outside_workspace,
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


# Issue #47: a tool-call audit record never carries the full result text —
# only a short preview and its length. The real payload already goes to
# `workspace/data/` via `save_tool_result` for the tools that matter;
# re-logging it in full here would reintroduce exactly what issue #46
# fixed (an uncontrolled-size payload held/passed around), for every tool
# instead of just holdings.
_RESULT_PREVIEW_MAX_CHARS = 200


def _tool_call_record(
    tool_use_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    matched: bool,
    is_error: bool | None,
    text: str | None,
) -> dict[str, Any]:
    """One line of the tool-call audit log. `matched=False` means no
    `ToolResultBlock` ever arrived for this call by the time the turn's
    stream ended (`status="no_result"`) — kept separate from `is_error`,
    since a real `ToolResultBlock.is_error` is itself `None` on an
    ordinary success (the SDK's own default), not just on a missing
    result; conflating the two previously misclassified every successful
    call as `"no_result"`."""
    if not matched:
        status = "no_result"
    elif is_error:
        status = "error"
    else:
        status = "completed"
    return {
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "status": status,
        "is_error": bool(is_error) if matched else None,
        "result_preview": text[:_RESULT_PREVIEW_MAX_CHARS] if text is not None else None,
        "result_length": len(text) if text is not None else None,
    }


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
        self.last_tool_calls: list[dict[str, Any]] = []

    async def send(
        self,
        prompt: str,
        *,
        workspace_root: Path | None = None,
        engine_log_path: Path | None = None,
    ) -> AsyncIterator[str]:
        """`workspace_root`, when given, turns on auto-capture: every Layer-2
        MCP tool result this turn produces is saved to the workspace's
        `data/` under the same filename its skill's own SKILL.md already
        documents (see engine/tool_capture.py) — the model no longer has to
        remember to save it there itself.

        Also mechanically appends a Sources footer + the SEBI disclaimer
        (see engine/sources_footer.py) once the turn's own text is fully
        streamed, if `workspace_root` is set, this turn captured at least
        one file, and the model's own text doesn't already contain one —
        docs/vision.md §5 requires both on every grounded output.
        Originally added because live-testing found the model reliably
        didn't write either on its own (the same class of dropped-closing-
        step failure `update_workspace_notes` fixed for notes.md); every
        skill's SKILL.md was later updated to explicitly say not to write
        one (issue #27, since appending on top of a self-authored one just
        duplicates it) — but that's prose, and prose isn't reliably
        followed either direction (issue #31 found the same), so this
        checks for the model's own disclaimer text and skips the append
        rather than trusting the instruction alone. A turn that captured
        nothing (plain chat, a workspace-less turn) gets no footer either
        way — see `build_footer`'s own docstring.

        Resets this session's per-turn tool-call counter (see
        engine/tool_budget.py) before sending — a skill's declared call
        expectation (e.g. morning-digest's india_news.get_news count)
        applies per turn, not cumulatively across a whole session. Never
        blocks a call; `last_over_budget` after the turn just lists which
        budgeted tools, if any, ran over — an audit signal, not
        enforcement (see engine/tool_budget.py's docstring for why).

        `last_tool_calls` after the turn holds one record per tool call
        attempted this turn — name, input, and a short status (completed/
        error/no_result), never the full result text (issue #47). This is
        every call, allowed or denied, unlike `last_captures` above which
        only ever reflects known, successful, capture-worthy results.
        Callers with a `workspace_root` write this to a durable per-session
        audit log (engine/tool_audit.py); this method only collects it.

        `engine_log_path`, when given, is threaded straight to
        `save_tool_result` (engine/tool_capture.py) — the durable home for
        this turn's routine diagnostics (issue #37), e.g. a rejected
        capture. Purely a pass-through; this method doesn't inspect it.

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
        tool_calls: list[dict[str, Any]] = []
        staged_output: str | None = None
        # Every yield below lands in the same concatenated stream — printed
        # verbatim, back to back, by interactive.py's `print(chunk, end="")`
        # and joined the same way for the saved transcript. A turn can
        # legitimately span several separate AssistantMessages (narration
        # before one tool-call round, then more narration after the next),
        # and nothing guarantees the first ends in whitespace before the
        # next begins, so without a separator they glue together mid-sentence
        # ("holdings.Identity matches...", issue #28). Every message's first
        # chunk gets a blank-line prefix once a prior chunk has already been
        # yielded — but only at that message boundary, not between two
        # TextBlocks *within* the same AssistantMessage.content, which can
        # legitimately be adjacent streamed fragments of one continuous
        # sentence (see test_claude_session_yields_text_blocks_in_order_and_
        # records_success's "Hi " + "there" case) that must concatenate
        # directly. `build_footer` already opens with its own "\n\n---\n" so
        # it doesn't need this prefix either way.
        first_chunk = True
        # Accumulates this turn's own (non-staged) text as it's yielded, so
        # the footer-appending check below can tell whether the model
        # already closed with its own disclaimer despite its skill's
        # `SKILL.md` saying not to — see that check's own comment.
        emitted_parts: list[str] = []
        async for message in self._client.receive_response():
            kind = type(message).__name__
            if kind == "AssistantMessage":
                message_start = True
                for block in message.content:
                    block_kind = type(block).__name__
                    if block_kind == "TextBlock":
                        if staged_output is None:
                            needs_separator = message_start and not first_chunk
                            chunk = f"\n\n{block.text}" if needs_separator else block.text
                            yield chunk
                            emitted_parts.append(chunk)
                            first_chunk = False
                            message_start = False
                    elif block_kind == "ToolUseBlock":
                        pending_tool_calls[block.id] = (block.name, block.input)
                        self._budget_tracker.record(block.name)
            elif kind == "UserMessage":
                for block in getattr(message, "content", None) or []:
                    if type(block).__name__ != "ToolResultBlock":
                        continue
                    # Popped, not just read — issue #47: whatever's left in
                    # pending_tool_calls once the stream ends never got a
                    # result at all, and becomes its own "no_result" audit
                    # record below.
                    call = pending_tool_calls.pop(block.tool_use_id, None)
                    if call is None:
                        continue
                    tool_name, tool_input = call
                    text = _tool_result_text(block.content)
                    tool_calls.append(
                        _tool_call_record(
                            block.tool_use_id,
                            tool_name,
                            tool_input,
                            matched=True,
                            is_error=block.is_error,
                            text=text,
                        )
                    )
                    if block.is_error:
                        # Issue #46's untrustworthy-capture guard and the
                        # staged-workflow branch below are both only ever
                        # meaningful for a real, successful result — an
                        # error/denied result (e.g. a PreToolUse hook's
                        # permissionDecisionReason) has nothing further to
                        # process once it's in the audit record above.
                        continue
                    parsed = parse_mcp_tool_name(tool_name)
                    if parsed is not None and parsed[0] == STAGED_WORKFLOWS_SERVER_NAME:
                        if text is not None:
                            staged_output = text
                            yield text if first_chunk else f"\n\n{text}"
                            first_chunk = False
                        continue
                    if workspace_root is None:
                        continue
                    if text is None:
                        continue
                    saved_path = save_tool_result(
                        tool_name, tool_input, text, workspace_root, engine_log_path=engine_log_path
                    )
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

        # Issue #47: any ToolUseBlock still here never got a matching
        # ToolResultBlock before the turn's stream ended — a genuinely
        # unusual case (e.g. the turn was interrupted mid-call), logged as
        # its own status rather than silently dropped.
        for tool_use_id, (tool_name, tool_input) in pending_tool_calls.items():
            tool_calls.append(
                _tool_call_record(tool_use_id, tool_name, tool_input, matched=False, is_error=None, text=None)
            )

        self.last_captures = captures
        self.last_tool_calls = tool_calls
        self.last_over_budget = self._budget_tracker.over_budget()
        # Every skill's SKILL.md now says not to write a closing footer/
        # disclaimer itself (issue #27) — but that's a prose instruction,
        # and this codebase has already found (issue #31) that prose
        # instructions aren't reliably followed either direction. This is
        # the structural backstop: if the model wrote one anyway, appending
        # a second, correct one on top would still be a visible duplicate
        # — skip it rather than stack it.
        already_has_disclaimer = DISCLAIMER in "".join(emitted_parts)
        if staged_output is None and workspace_root is not None and captures and not already_has_disclaimer:
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

        Also writes this one turn's tool-call audit log (issue #47) when
        `workspace_root` is set — each single-shot call gets its own audit
        file, named by its own start time (there's no shared multi-turn
        session timestamp to reuse here, unlike `_repl`). Written before
        the result-status checks below so a failed turn's tool-call trail
        is still captured, not just a successful one's — arguably more
        useful for the unattended/scheduled runs this path is built for,
        since nobody's watching stdout there to notice a diagnostic line.
        """
        try:
            async with self.open_session(tools) as session:
                chunks: list[str] = []
                async for chunk in session.send(prompt, workspace_root=workspace_root):
                    chunks.append(chunk)
                for line in session.last_over_budget:
                    print(f"[budget] {line}")
                if workspace_root is not None:
                    try:
                        append_tool_calls(new_audit_log_path(workspace_root), session.last_tool_calls)
                    except OSError as exc:
                        # Audit-only side effect — must never take the
                        # primary run down with it (same convention as
                        # engine/interactive.py's transcript-write guard).
                        print(f"[audit] couldn't write tool-call log: {exc}", file=sys.stderr)
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
