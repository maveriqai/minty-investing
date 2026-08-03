"""Headless, single-shot Minty engine entrypoint.

Usage: `uv run python -m engine.run "<prompt>"`

Must be run as a module (`-m`), not a direct script path — `python
engine/run.py` puts `engine/` itself on `sys.path` rather than the repo
root, so `from engine.guardrail import ...` fails with
`ModuleNotFoundError`.

For scripted/on-demand invocations (e.g. the digest) that don't need
multi-turn state. For a real conversation, see `engine/interactive.py`.
"""

from __future__ import annotations

import asyncio
import sys

from engine.config import build_tool_config
from engine.harnesses.base import Harness
from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness


async def _main(prompt: str, harness: Harness | None = None) -> int:
    # harness defaults to the SDK-backed implementation; tests can inject a
    # fake one satisfying the same Harness protocol, proving this module
    # only ever depends on that protocol, never the concrete SDK class.
    harness = harness or ClaudeAgentSDKHarness()
    result = await harness.run(prompt, build_tool_config())
    if result.ok:
        print(result.text)
        return 0
    print(f"engine run failed: {result.error_kind}", file=sys.stderr)
    return 1


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: uv run python -m engine.run "<prompt>"', file=sys.stderr)
        sys.exit(2)
    prompt = " ".join(sys.argv[1:])
    sys.exit(asyncio.run(_main(prompt)))


if __name__ == "__main__":
    main()
