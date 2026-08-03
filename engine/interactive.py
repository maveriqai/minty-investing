"""Minty's own interactive entrypoint — a real multi-turn conversation, not
"open Claude Code in this repo." This is Phase 1B step 3 from the old
repo's roadmap (never built there) and the one precondition for Track 1
("Minty as a standalone product," docs/vision.md §2) existing at all.

Usage: `uv run python -m engine.interactive`
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from engine.config import build_tool_config
from engine.harnesses.base import Harness
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness
from engine.workspace import changed_since, resolve_workspace, snapshot

_EXIT_COMMANDS = {"exit", "quit", ":q"}
_WORKSPACE_PREFIX = "/workspace "


def _augment_with_workspace(prompt: str, workspace_root: Path) -> str:
    """Tells the model exactly where the active workspace lives instead of
    leaving it to infer/choose a path from prose — see engine/workspace.py's
    docstring for why."""
    return (
        f"[Active workspace: {workspace_root} — already created by the "
        f"engine, not something to create yourself. Use this exact path for "
        f"any workspace file reads/writes this turn.]\n\n{prompt}"
    )


async def _run_turn(session, prompt: str, *, workspace_root: Path | None = None) -> None:
    before = snapshot(workspace_root) if workspace_root is not None else None
    sent = _augment_with_workspace(prompt, workspace_root) if workspace_root is not None else prompt
    async for chunk in session.send(sent):
        print(chunk, end="", flush=True)
    print()
    result = session.last_result
    if result is not None and not result.ok:
        print(f"[turn ended without success: {result.error_kind}]", file=sys.stderr)
    if workspace_root is not None:
        changed = changed_since(workspace_root, before)
        if changed:
            print(f"[workspace {workspace_root.name}: files changed — {', '.join(changed)}]")
        else:
            print(f"[workspace {workspace_root.name}: no files changed this turn]")


async def _repl(harness: Harness) -> int:
    tools = build_tool_config()
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
            await _run_turn(session, prompt, workspace_root=workspace_root)
    return 0


def main() -> None:
    sys.exit(asyncio.run(_repl(ClaudeAgentSDKHarness())))


if __name__ == "__main__":
    main()
