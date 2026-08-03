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
from engine.config import build_tool_config
from engine.harnesses.base import Harness, ToolConfig
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness
from engine.workspace import FIXED_WATCH_ROOTS, changed_since_all, resolve_workspace, snapshot_all

_EXIT_COMMANDS = {"exit", "quit", ":q"}
_WORKSPACE_PREFIX = "/workspace "
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


def _report_changed_files(changed: list[str], skill_names: list[str], workspace_name: str | None) -> None:
    """Factual, generic report — doesn't know or guess which skill (if any)
    the turn invoked, just checks whatever changed against every loaded
    skill's declared `expected_outputs` (see engine/skills.py). A skill
    that declares nothing is silently not checked, not flagged as missing.
    """
    if not changed:
        print("[no files changed this turn]")
        return

    today = datetime.now(_IST).date().isoformat()
    matched_files: set[str] = set()
    for name in skill_names:
        matches = skills.match_changed_files(name, changed, workspace_name=workspace_name, date=today)
        if matches:
            matched_files.update(matches)
            print(f"[matches {name}'s expected output — {', '.join(matches)}]")

    unmatched = [f for f in changed if f not in matched_files]
    if unmatched:
        print(f"[other files changed, not matching any known skill's expected output — {', '.join(unmatched)}]")


async def _run_turn(
    session,
    prompt: str,
    *,
    workspace_root: Path | None = None,
    skill_names: list[str] | None = None,
) -> None:
    before = snapshot_all(FIXED_WATCH_ROOTS)
    sent = _augment_with_workspace(prompt, workspace_root) if workspace_root is not None else prompt
    async for chunk in session.send(sent):
        print(chunk, end="", flush=True)
    print()
    result = session.last_result
    if result is not None and not result.ok:
        print(f"[turn ended without success: {result.error_kind}]", file=sys.stderr)
    changed = changed_since_all(FIXED_WATCH_ROOTS, before)
    _report_changed_files(changed, skill_names or [], workspace_root.name if workspace_root else None)


async def _repl(harness: Harness) -> int:
    tools: ToolConfig = build_tool_config()
    skill_names = tools.skills if isinstance(tools.skills, list) else []
    print(
        "Minty — connected. Type a message, 'exit' to quit, "
        "or '/workspace <name>' to set the active workspace."
    )
    workspace_root: Path | None = None
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
            if prompt.startswith(_WORKSPACE_PREFIX):
                name = prompt[len(_WORKSPACE_PREFIX) :].strip()
                if not name:
                    print("usage: /workspace <name>", file=sys.stderr)
                    continue
                workspace_root = resolve_workspace(name)
                print(f"[workspace set: {workspace_root}]")
                continue
            print("minty> ", end="", flush=True)
            await _run_turn(session, prompt, workspace_root=workspace_root, skill_names=skill_names)
    return 0


def main() -> None:
    sys.exit(asyncio.run(_repl(ClaudeAgentSDKHarness())))


if __name__ == "__main__":
    main()
