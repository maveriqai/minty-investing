"""Minty's own interactive entrypoint — a real multi-turn conversation, not
"open Claude Code in this repo." This is Phase 1B step 3 from the old
repo's roadmap (never built there) and the one precondition for Track 1
("Minty as a standalone product," docs/vision.md §2) existing at all.

Usage: `uv run python -m engine.interactive`
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import skills
from engine.claude_login import ensure_logged_in
from engine.config import build_tool_config
from engine.harnesses.base import Harness, ToolConfig
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness
from engine.kite_status import kite_connection_status_line
from engine.workspace import (
    FIXED_WATCH_ROOTS,
    REPO_ROOT,
    changed_since_all,
    resolve_active_workspace,
    snapshot_all,
)

_EXIT_COMMANDS = {"exit", "quit", ":q"}
_IST = ZoneInfo("Asia/Kolkata")


def _augment_with_workspace(prompt: str, workspace_root: Path) -> str:
    """Tells the model exactly where the active workspace lives instead of
    leaving it to infer/choose a path from prose — see engine/workspace.py's
    docstring for why."""
    return (
        f"[Active workspace: {workspace_root} — already created by the "
        f"engine, not something to create yourself. Use this exact path for "
        f"any workspace file reads/writes this turn.]\n\n{prompt}"
    )


def _workspace_name(workspace_root: Path) -> str:
    """`workspace_root`'s own path relative to REPO_ROOT ("workspace", or
    ".dev-workspaces/<name>" under MINTY_WORKSPACE) — what a skill's own
    `{workspace}`-placeholder patterns (engine/skills.py) substitute in.
    Falls back to the bare directory name if `workspace_root` isn't under
    this repo at all (a test double standing in for a real workspace) —
    that fallback never fires in production, where every real
    workspace_root always is."""
    try:
        return str(workspace_root.relative_to(REPO_ROOT))
    except ValueError:
        return workspace_root.name


def _report_changed_files(
    changed: list[str], skill_names: list[str], workspace_name: str | None, *, date: str
) -> None:
    """Factual, generic report — doesn't know or guess which skill (if any)
    the turn invoked, just checks whatever changed against every loaded
    skill's declared `expected_outputs` (see engine/skills.py). A skill
    that declares nothing is silently not checked, not flagged as missing.
    """
    if not changed:
        print("[no files changed this turn]")
        return

    matched_files: set[str] = set()
    for name in skill_names:
        matches = skills.match_changed_files(name, changed, workspace_name=workspace_name, date=date)
        if matches:
            matched_files.update(matches)
            print(f"[matches {name}'s expected output — {', '.join(matches)}]")

    unmatched = [f for f in changed if f not in matched_files]
    if unmatched:
        print(f"[other files changed, not matching any known skill's expected output — {', '.join(unmatched)}]")


def _save_composed_outputs(
    full_text: str,
    changed: list[str],
    skill_names: list[str],
    *,
    workspace_name: str,
    date: str,
) -> None:
    """For any loaded skill whose own (non-`.md`) `expected_outputs`
    pattern matched a file that changed this turn — proof its
    deterministic step actually ran, e.g. `digest_math.py` writing
    `results/digest_<date>.json` — also write that skill's declared `.md`
    pattern (see `skills.composed_output_patterns`) with the turn's full
    composed text, including the engine-appended Sources footer.

    Fixes morning-digest step 10 ("save a copy of the composed brief")
    being a prose-only instruction the model reliably didn't follow (found
    live 2026-08-04) — same "engine writes it, not model prose" shape as
    engine/sources_footer.py and engine/workspace_notes.py. No morning-
    digest-specific code: any skill that declares both a `.json` and a
    `.md` expected output gets this for free the moment its
    script-computed half shows up.

    A no-op, not an error, when `full_text` is blank (a turn with no
    reply text has nothing worth archiving) or no skill's non-`.md`
    pattern matched (an ordinary chat turn, or a skill with no `.md`
    deliverable declared at all).
    """
    if not full_text.strip():
        return
    for name in skill_names:
        md_patterns = skills.composed_output_patterns(name)
        if not md_patterns:
            continue
        if not skills.match_changed_files(name, changed, workspace_name=workspace_name, date=date):
            continue
        for pattern in md_patterns:
            resolved = skills.resolve_pattern(pattern, workspace_name=workspace_name, date=date)
            if "{workspace}" in resolved:
                continue
            path = skills.REPO_ROOT / resolved
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(full_text)
            print(f"[engine saved {name}'s composed output — {path}]")


async def _run_turn(
    session,
    prompt: str,
    *,
    workspace_root: Path | None = None,
    skill_names: list[str] | None = None,
) -> None:
    before = snapshot_all(FIXED_WATCH_ROOTS)
    sent = _augment_with_workspace(prompt, workspace_root) if workspace_root is not None else prompt
    chunks: list[str] = []
    async for chunk in session.send(sent, workspace_root=workspace_root):
        print(chunk, end="", flush=True)
        chunks.append(chunk)
    print()
    result = session.last_result
    if result is not None and not result.ok:
        print(f"[turn ended without success: {result.error_kind}]", file=sys.stderr)
    for line in getattr(session, "last_over_budget", []):
        print(f"[budget] {line}")
    today = datetime.now(_IST).date().isoformat()
    changed = changed_since_all(FIXED_WATCH_ROOTS, before)
    if workspace_root is not None:
        workspace_name = _workspace_name(workspace_root)
        _save_composed_outputs("".join(chunks), changed, skill_names or [], workspace_name=workspace_name, date=today)
        changed = changed_since_all(FIXED_WATCH_ROOTS, before)
    else:
        workspace_name = None
    _report_changed_files(changed, skill_names or [], workspace_name, date=today)


async def _repl(harness: Harness, workspace_root: Path) -> int:
    tools: ToolConfig = build_tool_config()
    skill_names = tools.skills if isinstance(tools.skills, list) else []
    print("Minty — connected. Type a message, 'exit' to quit.")
    async with harness.open_session(tools) as session:
        while True:
            try:
                prompt = await asyncio.to_thread(input, "you> ")
            except EOFError:
                print()
                break
            prompt = prompt.strip()
            if not prompt:
                continue
            if prompt.lower() in _EXIT_COMMANDS:
                break
            print("minty> ", end="", flush=True)
            await _run_turn(session, prompt, workspace_root=workspace_root, skill_names=skill_names)
    return 0


def main() -> None:
    # Checked here, before any prompt is shown, so a stale/missing login
    # never lands the user in a bare `claude` chat instead of Minty's own
    # engine — see engine/claude_login.py's docstring for the live-found
    # bug this closes.
    if not ensure_logged_in():
        print("Couldn't sign in to Claude — run 'claude auth login' and try again.", file=sys.stderr)
        sys.exit(1)
    # The one fixed, unnamed workspace for this install (docs/next-phase-plan.md
    # §4) — resolved before the REPL ever starts, same "check before printing
    # anything" shape as the Claude-login check above, so the Kite status
    # line below can read its holdings snapshot.
    workspace_root = resolve_active_workspace()
    print(kite_connection_status_line(workspace_root))
    sys.exit(asyncio.run(_repl(ClaudeAgentSDKHarness(), workspace_root)))


if __name__ == "__main__":
    main()
