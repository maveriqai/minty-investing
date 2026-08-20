"""Headless, single-shot Minty engine entrypoint.

Usage: `uv run python -m engine.run "<prompt>"`

Must be run as a module (`-m`), not a direct script path — `python
engine/run.py` puts `engine/` itself on `sys.path` rather than the repo
root, so `from engine.guardrail import ...` fails with
`ModuleNotFoundError`.

For scripted/on-demand invocations (e.g. the digest) that don't need
multi-turn state. For a real conversation, see `engine/interactive.py`.

Always resolves and threads the one active workspace (the fixed `workspace/`
per docs/next-phase-plan.md §4, or a `MINTY_WORKSPACE`-named dev sandbox) —
this used to be an opt-in `--workspace <name>` flag, and omitting it
silently meant no auto-capture, no Sources footer, and no SEBI disclaimer
at all (found live 2026-08-08 running `portfolio-health-check`/
`red-flag-scan` this way). Making the workspace always-active closes that
gap by construction instead of relying on the caller to remember the flag.
"""

from __future__ import annotations

import asyncio
import sys

from engine.config import build_tool_config
from engine.harnesses.base import Harness
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness
from engine.interactive import _augment_with_workspace
from engine.workspace import resolve_active_workspace


async def _main(prompt: str, harness: Harness | None = None) -> int:
    # harness defaults to the SDK-backed implementation; tests can inject a
    # fake one satisfying the same Harness protocol, proving this module
    # only ever depends on that protocol, never the concrete SDK class.
    harness = harness or ClaudeAgentSDKHarness()
    workspace_root = resolve_active_workspace()
    sent = _augment_with_workspace(prompt, workspace_root)
    result = await harness.run(sent, build_tool_config(), workspace_root=workspace_root)
    if result.ok:
        print(result.text)
        return 0
    print(f"engine run failed: {result.error_kind}", file=sys.stderr)
    return 1


def main() -> None:
    args = sys.argv[1:]
    usage = 'usage: uv run python -m engine.run "<prompt>"'
    if not args:
        print(usage, file=sys.stderr)
        sys.exit(2)
    prompt = " ".join(args)
    sys.exit(asyncio.run(_main(prompt)))


if __name__ == "__main__":
    main()
