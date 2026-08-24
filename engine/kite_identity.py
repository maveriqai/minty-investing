"""Deterministic, engine-owned half of the Zerodha account-identity check —
issue #19.

`engine/tool_capture.py` already makes `data/account_identity.json`
write-once, so no tool call can ever silently redirect Minty at a
different account. What that alone doesn't do is *use* the anchor:
comparing a live `get_profile` response against it and stopping before a
mismatched account's holdings/positions get fetched. Until now that
compare-and-stop logic was pure prose, repeated in three skills' own
`SKILL.md` steps — it depended on the model reading the anchor, calling
`get_profile`, comparing, and refusing correctly every single time, the
same category of model-judgement dependency the write-once anchor design
was built specifically to avoid for the *write* side (see
`docs/next-phase-plan.md` §4's three-design history).

This module backs a `PostToolUse` hook (records the live `user_id` the
moment `get_profile` returns) and a `PreToolUse` hook (hard-denies
`get_holdings`/`get_positions` once a mismatch is confirmed) in
`engine/harnesses/claude_agent_sdk.py` — the same hard-deny-hook shape
already used for the six order tools.

Deliberately narrow scope, and deliberately fail-open, not fail-closed:

- Only denies on a *confirmed* mismatch (a successfully parsed live
  `user_id` that disagrees with a successfully parsed anchor). It does
  *not* deny merely because no `get_profile` call has happened yet this
  session — that would make correctness here depend on this module
  correctly parsing a live `tool_response` whose exact shape isn't pinned
  down by any published schema (`PostToolUse` hooks are dispatched by the
  `claude` CLI subprocess itself, outside this repo, and this hasn't been
  live-verified against a real Kite session yet). A wrong guess about
  that shape would otherwise permanently block every holdings fetch for
  every user — a far worse outage than the rare account-mismatch this
  module exists to catch. Closing that "was a check even attempted"
  coverage gap (issue #6) stays on the softer, already-shipped
  system-prompt nudge until this has been live-verified and can safely be
  hardened.
- Only gates `get_holdings`/`get_positions` — the two kite_gateway tools
  that either persist to disk (`get_holdings`, the one kite_gateway tool
  `CAPTURE_SPECS` writes to `workspace/data/`) or surface real-money
  figures to the user (`get_positions`). Broaden only if a real gap
  surfaces, not preemptively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from engine import kite_status

IDENTITY_GATED_TOOLS = frozenset({"get_holdings", "get_positions"})


def _user_id_from_data(data: Any) -> str | None:
    """Same "flat dict vs. list-of-content-blocks" ambiguity
    `kite_status.anchor_user_id` handles for the anchor file — a live
    `get_profile` response can take either shape too (see that function's
    docstring for the live-confirmed reason)."""
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
    leave state as-is", never as a mismatch. NOT YET LIVE-VERIFIED; see
    this module's own docstring."""
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
        audit-only-but-visible pattern: this module's own docstring admits
        the real `tool_response` shape isn't live-verified yet, so a
        silent parse failure here would otherwise mean the whole mismatch
        check is quietly inert with nothing anywhere to reveal that. True
        for every other outcome, including the normal "no anchor to
        compare against yet" case, which is expected, not a failure."""
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
