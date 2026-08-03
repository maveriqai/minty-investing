"""Minty's own interactive entrypoint — a real multi-turn conversation, not
"open Claude Code in this repo." This is Phase 1B step 3 from the old
repo's roadmap (never built there) and the one precondition for Track 1
("Minty as a standalone product," docs/vision.md §2) existing at all.

Usage: `uv run python -m engine.interactive`
"""

from __future__ import annotations

import asyncio
import sys

from engine.config import build_tool_config
from engine.harnesses.base import Harness
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness

_EXIT_COMMANDS = {"exit", "quit", ":q"}


async def _run_turn(session, prompt: str) -> None:
    async for chunk in session.send(prompt):
        print(chunk, end="", flush=True)
    print()
    result = session.last_result
    if result is not None and not result.ok:
        print(f"[turn ended without success: {result.error_kind}]", file=sys.stderr)


async def _repl(harness: Harness) -> int:
    tools = build_tool_config()
    print("Minty — connected. Type a message, or 'exit' to quit.")
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
            await _run_turn(session, prompt)
    return 0


def main() -> None:
    sys.exit(asyncio.run(_repl(ClaudeAgentSDKHarness())))


if __name__ == "__main__":
    main()
