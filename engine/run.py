"""Headless, single-shot Minty engine entrypoint.

Usage: `uv run python -m engine.run "<prompt>"`
       `uv run python -m engine.run --workspace <name> "<prompt>"`

Must be run as a module (`-m`), not a direct script path — `python
engine/run.py` puts `engine/` itself on `sys.path` rather than the repo
root, so `from engine.guardrail import ...` fails with
`ModuleNotFoundError`.

For scripted/on-demand invocations (e.g. the digest) that don't need
multi-turn state. For a real conversation, see `engine/interactive.py`.

`--workspace <name>` matters beyond convenience: without it, this
single-shot path gets no auto-capture, no Sources footer, and no SEBI
disclaimer at all, silently — found live 2026-08-08 running
`portfolio-health-check`/`red-flag-scan` this way. `Harness.run()`'s
`workspace_root` only turns those on when actually given, matching
`engine/interactive.py`'s own `_run_turn`, which is why this reuses that
module's `_augment_with_workspace` rather than re-deriving the same
prompt-prefix convention here.
"""

from __future__ import annotations

import asyncio
import sys

from engine.config import build_tool_config
from engine.harnesses.base import Harness
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness
from engine.interactive import _augment_with_workspace
from engine.workspace import resolve_workspace


async def _main(prompt: str, harness: Harness | None = None, *, workspace_name: str | None = None) -> int:
    # harness defaults to the SDK-backed implementation; tests can inject a
    # fake one satisfying the same Harness protocol, proving this module
    # only ever depends on that protocol, never the concrete SDK class.
    harness = harness or ClaudeAgentSDKHarness()
    workspace_root = resolve_workspace(workspace_name) if workspace_name is not None else None
    sent = _augment_with_workspace(prompt, workspace_root) if workspace_root is not None else prompt
    result = await harness.run(sent, build_tool_config(), workspace_root=workspace_root)
    if result.ok:
        print(result.text)
        return 0
    print(f"engine run failed: {result.error_kind}", file=sys.stderr)
    return 1


def main() -> None:
    args = sys.argv[1:]
    usage = 'usage: uv run python -m engine.run [--workspace <name>] "<prompt>"'
    workspace_name: str | None = None
    if args[:1] == ["--workspace"]:
        if len(args) < 3:
            print(usage, file=sys.stderr)
            sys.exit(2)
        workspace_name = args[1]
        args = args[2:]
    if not args:
        print(usage, file=sys.stderr)
        sys.exit(2)
    prompt = " ".join(args)
    sys.exit(asyncio.run(_main(prompt, workspace_name=workspace_name)))


if __name__ == "__main__":
    main()
