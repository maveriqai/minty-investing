"""The seam between Minty's own orchestration and any concrete model/
provider integration ("harness").

`ClaudeAgentSDKHarness` (claude_agent_sdk.py) is the first and, for now,
only implementation — see docs/vision.md §3/§4 for why a second backend
(Codex, named as the example) stays a documented seam rather than
something built now. Nothing outside `harnesses/` should need to know
which concrete harness is in use; callers only ever talk to the `Harness`
protocol below.

`Session` is the piece the old Minty engine never had: a connected,
stateful conversation that holds context across multiple calls to
`send()`, instead of one `run()` call per process. It's what makes Track 1
("Minty as a standalone product," docs/vision.md §2) a real tool rather
than a single-shot script — every prior engine build (including this
project's own predecessor) stopped at single-shot.

Known limitation, not solved by this seam: skill loading is delegated to
each harness's own native mechanism (the Claude Agent SDK's
`setting_sources`/`skills`, for `ClaudeAgentSDKHarness`). A future harness
without an equivalent would need its own skill-loading translation — not
designed here, since building a bespoke harness-agnostic skill loader
before a second harness actually needs one would be speculative.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from engine.guardrail import GuardrailPolicy


@dataclass(frozen=True)
class ToolConfig:
    """Harness-agnostic description of what a run is allowed to touch.

    `mcp_servers` uses the same shape as `.mcp.json`'s `"mcpServers"` value
    (a dict keyed by server name, stdio or http entries) — every current
    harness implementation is expected to accept that shape directly or
    translate it into its own native form.
    """

    mcp_servers: dict[str, Any]
    guardrail: GuardrailPolicy
    skills: str | list[str]

    # `permission_mode="bypassPermissions"` auto-approves every built-in tool
    # (Bash, Edit, WebFetch, ...) before any allow/deny check — the free
    # scoping a TTY session's default permission mode gives for nothing is
    # gone once bypass is on, including in interactive Sessions (see
    # claude_agent_sdk.py's docstring for why bypass is used there too, not
    # just for headless single-shot runs). These three fields are how a
    # caller gets it back, via mechanisms that still fire under bypass (a
    # restricted `tools` list, and a deny-based hook — allow-lists like
    # `allowed_tools` are silently inert under bypassPermissions, only deny
    # mechanisms aren't).
    builtin_tools: list[str] | None = None  # None = SDK default (every built-in tool)
    allowed_bash_prefixes: tuple[str, ...] = ()  # enforced by a PreToolUse hook, not an allow-list
    max_buffer_size: int | None = None  # None = SDK's own default (1MB)

    # A staged skill (docs/staged-skill-execution-design.md) is exposed via
    # its own run_staged_<skill> tool, never through native Skill-invocation
    # — see engine/harnesses/claude_agent_sdk.py's _build_options. That tool
    # opens further sessions of its own; this flag is set False on the
    # ToolConfig passed to *those* inner sessions (engine/staged_skills.py)
    # so a stage's own session never sees run_staged_<skill> itself and
    # can't recursively re-trigger the whole staged run.
    include_staged_tools: bool = True


@dataclass(frozen=True)
class EngineResult:
    """Normalized outcome of one turn, independent of which harness
    produced it."""

    ok: bool
    text: str | None
    error_kind: str | None  # e.g. "session_limit", "other" — None when ok
    raw: object  # harness-native result/exception, for debugging only


class Session(Protocol):
    """A connected, stateful conversation. One instance holds conversation
    history across multiple `send()` calls — the harness/SDK's own session
    object underneath, not something Minty reimplements.

    `last_result` reflects the most recently completed turn once `send()`'s
    iterator has been fully consumed — mirrors `EngineResult` from the
    single-shot `Harness.run()` path, so callers checking for
    success/failure use the same shape either way.
    """

    last_result: EngineResult | None

    def send(self, prompt: str) -> AsyncIterator[str]:
        """Send one turn, yielding assistant text as it streams in."""
        ...


class Harness(Protocol):
    async def run(self, prompt: str, tools: ToolConfig) -> EngineResult:
        """Single-shot: one prompt in, one result out, no session held
        open. Still useful for scripted/on-demand invocations (e.g. the
        digest) that don't need multi-turn state."""
        ...

    def open_session(self, tools: ToolConfig) -> AbstractAsyncContextManager[Session]:
        """Multi-turn: connects once, yields a `Session` that holds
        conversation state across calls, disconnects on exit."""
        ...
