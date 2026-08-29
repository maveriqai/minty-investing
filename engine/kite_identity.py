"""Deterministic, engine-owned half of the Zerodha account-identity check —
issue #19.

`engine/tool_capture.py` already makes `data/account_identity.json`
write-once, so no tool call can ever silently redirect Minty at a
different account. What that alone doesn't do is *use* the anchor:
comparing a live `get_profile` response against it and stopping before a
mismatched account's holdings/positions get fetched. Originally (issue
#19) that compare-and-stop logic was pure prose, repeated in three skills'
own `SKILL.md` steps — it depended on the model reading the anchor,
calling `get_profile`, comparing, and refusing correctly every single
time, the same category of model-judgement dependency the write-once
anchor design was built specifically to avoid for the *write* side (see
`docs/next-phase-plan.md` §4's three-design history). Live-verified
2026-08-29 that this was never actually fixed: the compare-and-stop
narration still came from the model's own prose, not from anything this
module surfaced — see issue #48.

As of #48, the comparison itself is a real tool
(`engine.identity_check.check_identity_match`) that the three skills call
directly instead of reading and comparing JSON themselves — it reuses
`IdentityGuardState`/`user_id_from_get_profile_response` below and returns
a structured `{"status", "anchor_user_id", "live_user_id"}` result. This
module's own hooks are now purely the backstop, not the primary path: a
`PostToolUse` hook (records the live `user_id` the moment any *direct*
`get_profile` call returns — `check_identity_match`'s own in-process call
updates the same shared state itself, see `engine/identity_check.py`) and
a `PreToolUse` hook (hard-denies `get_holdings`/`get_positions` once a
mismatch is confirmed, from either path) in
`engine/harnesses/claude_agent_sdk.py` — the same hard-deny-hook shape
already used for the six order tools.

Deliberately narrow scope, and deliberately fail-open, not fail-closed:

- Only denies on a *confirmed* mismatch (a successfully parsed live
  `user_id` that disagrees with a successfully parsed anchor). It does
  *not* deny merely because no `get_profile` call has happened yet this
  session — even though the `tool_response` shape this depends on is now
  live-verified (2026-08-25, a real ad hoc "what are my holdings" run —
  see `user_id_from_get_profile_response`'s docstring for the confirmed
  shape), hardening the "unchecked" branch to a hard deny is a separate
  design decision with its own real cost: it would add a mandatory
  extra `get_profile` round trip to every ad hoc holdings/positions
  query, not just protect against the rare account-mismatch case. Left
  as a deliberate follow-up, not done as a side effect of the shape now
  being confirmed. Closing that "was a check even attempted" coverage
  gap (issue #6) stays on the softer, already-shipped system-prompt
  nudge for now.
- Only gates `get_holdings`/`get_positions`/`fetch_holdings` — the
  kite_gateway tools that either persist to disk or surface real-money
  figures to the user. `get_holdings` itself is now unconditionally
  blocked from the model's tool inventory (issue #46) — `fetch_holdings`
  (`engine/holdings_fetch.py`) is the only remaining way to reach
  holdings data, so it's the practical gate for that persistence path
  today; `get_holdings` stays listed here too since the mismatch check is
  about the underlying capability, not which specific tool name currently
  exposes it. Broaden only if a real gap surfaces, not preemptively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from engine import kite_status

IDENTITY_GATED_TOOLS = frozenset({"get_holdings", "get_positions", "fetch_holdings"})


def _user_id_from_data(data: Any) -> str | None:
    """Same "flat dict vs. list-of-content-blocks" ambiguity
    `kite_status.anchor_user_id` handles for the anchor file — a live
    `get_profile` response can take either shape too (see that function's
    docstring for the live-confirmed reason).

    Takes only the *first* matching text block, unlike
    `claude_agent_sdk.py`'s `_tool_result_text` (which joins all of them) —
    this is extracting a single JSON envelope, and joining multiple JSON
    fragments together would almost certainly break `json.loads` anyway.
    Deliberate divergence, not drift — see issue #20."""
    if isinstance(data, list):
        text = next(
            (block.get("text") for block in data if isinstance(block, dict) and block.get("type") == "text"),
            None,
        )
        if text is None:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        user_id = data.get("user_id")
        return str(user_id) if user_id is not None else None
    return None


def user_id_from_get_profile_response(tool_response: Any) -> str | None:
    """Best-effort `user_id` extraction from a `PostToolUse` hook's raw
    `tool_response` for a `get_profile` call. Returns None on any shape
    this doesn't recognize — callers must treat that as "couldn't verify,
    leave state as-is", never as a mismatch.

    Live-confirmed 2026-08-25: `tool_response` for an MCP tool call is a
    plain JSON **string** — the same `{"source", "as_of", "data"}`
    envelope every Layer 2 tool returns, serialized to text, not a
    pre-parsed dict — e.g. `'{"source":"kite","as_of":"...",
    "data":[{"type":"text","text":"{\\"user_id\\":...}",...}]}'`. The
    `str`/`dict` shapes below are both handled defensively regardless,
    since nothing guarantees every MCP server or SDK version serializes
    this identically."""
    if isinstance(tool_response, str):
        try:
            tool_response = json.loads(tool_response)
        except json.JSONDecodeError:
            return None
    if not isinstance(tool_response, dict):
        return None
    if "data" in tool_response:
        return _user_id_from_data(tool_response["data"])
    content = tool_response.get("content")
    text: str | None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = next(
            (block.get("text") for block in content if isinstance(block, dict) and block.get("type") == "text"),
            None,
        )
    else:
        text = None
    if text is None:
        return None
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(envelope, dict) and "data" in envelope:
        return _user_id_from_data(envelope["data"])
    return None


@dataclass
class IdentityGuardState:
    """Mutable, session-scoped — one instance per `open_session()` call,
    shared by both hooks via closure so a check earlier in a multi-turn
    session still gates a later turn's call, not just the turn that did
    the checking. `mismatch` only ever moves False -> True: once a real
    mismatch is confirmed there is no in-session way back (matches the
    skills' own prose today — resolving it is a deliberate, out-of-band
    step, deleting `data/account_identity.json` by hand, not something
    reachable from inside a conversation), so `record_profile_response`
    below short-circuits once it's set rather than re-reading the anchor
    file on every later `get_profile` call for a verdict that can't
    change."""

    mismatch: bool = False
    _cached_anchor_user_id: str | None = field(default=None, repr=False)

    def record_profile_response(self, tool_response: Any) -> bool:
        """State unchanged if `tool_response` doesn't parse, or if there's
        no anchor yet to compare against — see this module's docstring for
        why an unparseable response must never be treated as a mismatch.

        Caches a *found* anchor `user_id` (safe: the anchor is write-once,
        so once read it can't change) but not its absence — a "no anchor
        yet" result must stay live, since the anchor can still get written
        later in the same session by this same `get_profile` call's own
        write-once capture (engine/tool_capture.py), and a stale cached
        None would then wrongly skip comparing against it on a later
        call.

        Returns False only when `tool_response` couldn't be parsed at all
        — the caller (`_build_identity_record_hook` in
        `engine/harnesses/claude_agent_sdk.py`) uses this to print a
        diagnostic, mirroring `engine/tool_budget.py`'s own
        audit-only-but-visible pattern: the parsed shape is now
        live-confirmed (see `user_id_from_get_profile_response`'s
        docstring), but nothing guarantees it stays that way forever (a
        future Kite/SDK response-shape change), so this stays as a
        standing canary rather than being removed now that it's proven
        once. True for every other outcome, including the normal "no
        anchor to compare against yet" case, which is expected, not a
        failure."""
        if self.mismatch:
            return True
        user_id = user_id_from_get_profile_response(tool_response)
        if user_id is None:
            return False
        anchor = self._cached_anchor_user_id
        if anchor is None:
            anchor = kite_status.anchor_user_id()
            if anchor is not None:
                self._cached_anchor_user_id = anchor
        if anchor is not None and anchor != user_id:
            self.mismatch = True
        return True


__all__ = [
    "IDENTITY_GATED_TOOLS",
    "IdentityGuardState",
    "user_id_from_get_profile_response",
]
