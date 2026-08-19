"""Preflight check for `minty`'s own terminal entrypoint (engine/interactive.py).

Minty's Agent-SDK session silently depends on the host already having a
working `claude` CLI login — see engine/harnesses/claude_agent_sdk.py's
docstring. Until now, the only documented recovery was "go run `claude`
yourself" (README's Onboarding step 1), which sends the user into a plain
Claude Code chat session. Found live 2026-08-14: a user who stayed in that
chat instead of exiting back to a shell typed `minty` as a *message*, and
Claude Code — sitting in this repo, with the same `.claude/skills/` and
`.mcp.json` it always reads for any project — improvised a lookalike
Minty using its own native Skill/tool-permission machinery, not Minty's
engine at all. None of Minty's own guarantees (Sources footer, SEBI
disclaimer, auto-capture, the engine-level order-tool deny-hook) apply on
that path; only Layer 1's tool-omission at the gateway still held.

This module closes the gap at the source: `minty` checks login itself
before ever handing control to a chat prompt, and if a login is needed,
runs `claude auth login` directly — not a full interactive `claude`
session — so there's no lingering chat for the user to get stuck in. The
user still completes the real OAuth flow in their own browser via that
command; this only changes who types the command, never who touches the
credentials.
"""

from __future__ import annotations

import json
import subprocess

_STATUS_TIMEOUT_S = 10.0


def is_logged_in() -> bool:
    """True if `claude auth status` reports a live login. Fails open (True)
    if the check itself can't run — a broken preflight shouldn't be the
    thing that stops `minty` from starting; worst case, the underlying
    session attempt fails the same way it always did before this module
    existed."""
    try:
        result = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=_STATUS_TIMEOUT_S,
            check=False,
        )
        return bool(json.loads(result.stdout).get("loggedIn"))
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return True


def ensure_logged_in() -> bool:
    """Returns True once a login is confirmed. If none is found, runs
    `claude auth login` — inheriting this process's stdio so the user sees
    and completes the real login prompt/URL — then re-checks. Returns
    False only if login was attempted and still didn't take, so the caller
    can stop before opening a session that would just fail the same way.

    Prints a one-line confirmation either way — found live 2026-08-19
    (real dogfooding, first fresh-clone run by hand): the already-
    logged-in path fell straight through to `minty`'s own "Minty —
    connected." with no acknowledgment of *what* had just been checked,
    while the not-logged-in path already prints "Connecting your Claude
    account...". Silence on the common (already-logged-in) path read as
    ambiguous, not as "everything's fine."
    """
    if is_logged_in():
        print("Claude account already connected.")
        return True
    print("Connecting your Claude account (one-time) ...")
    subprocess.run(["claude", "auth", "login"], check=False)
    return is_logged_in()
