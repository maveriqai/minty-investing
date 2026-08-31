"""Shared `ToolConfig` construction for engine entrypoints (`run.py`,
`interactive.py`) — kept in one place so single-shot and session mode can't
drift on MCP wiring, guardrail, or skill discovery.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import ToolConfig

REPO_ROOT = Path(__file__).parent.parent

# The SDK's stdio transport bounds one NDJSON message (a single tool
# result) at 1MB by default — not cumulative conversation size, one
# message. Found live porting red-flag-scan: a real run crashed with
# "JSON message exceeded maximum buffer size of 1048576 bytes" on its
# first real Layer 2 call. The old repo measured this properly rather than
# guessing: get_announcements with the exact yesterday/today bound
# measured 86 bytes-4KB for real symbols; a *mistaken* unbounded call (a
# plausible prompt-adherence slip, not just theoretical) measured
# 2.0-3.0MB for large-caps like TCS/RELIANCE/SBIN. 10MB gives comfortable
# headroom above that measured worst case. Applies engine-wide, not just
# to morning-digest — any skill pulling filings/news/shareholding data can
# hit this.
_MAX_BUFFER_SIZE = 10_000_000


def _minty_skill_names() -> list[str]:
    """Explicit skill list, not "all" — `skills="all"` also pulls in
    unrelated global/user-level skills installed on the host, which a
    Minty-dedicated engine shouldn't surface. Empty list (not an error) if
    `.claude/skills/` doesn't exist — lets the engine still run for plain
    conversation and Layer 1/2 tool use even before any skill is ported.

    Reads `.claude/skills/`, not the top-level `skills/` directory —
    corrected after live-testing this port. `docs/vision.md` §4 originally
    assumed the engine could read canonical `skills/` directly since it
    "owns skill loading, not bound to Claude Code's discovery." Verified
    live that this is false at the plumbing level:
    `setting_sources=["project"]` + `skills=[...]` *is* Claude Code's own
    project-skill discovery (the Agent SDK's transport shells out to the
    `claude` CLI, see claude_agent_sdk.py's docstring), and that mechanism
    only ever reads `.claude/skills/` — confirmed by dumping a live
    `SystemMessage`'s own `skills` field, which listed unrelated host/CLI
    skills and *not* this project's own until `.claude/skills/` (not
    `skills/`) held the same content. `skills/` still exists for
    `README.md`/`THIRD-PARTY-NOTICES.md`; the actual skill packages
    (SKILL.md + scripts/) live only in `.claude/skills/` now — one
    canonical copy, not the old repo's canonical-plus-generated-view split
    (there's no second harness needing a different structure yet to
    justify that machinery — see docs/vision.md §3's Codex section).
    """
    skills_dir = REPO_ROOT / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def build_tool_config(
    *, builtin_tools: list[str] | None = None, max_buffer_size: int | None = None
) -> ToolConfig:
    mcp_config = json.loads((REPO_ROOT / ".mcp.json").read_text())
    return ToolConfig(
        mcp_servers=mcp_config["mcpServers"],
        guardrail=GuardrailPolicy(),
        skills=_minty_skill_names(),
        # bypassPermissions (required for headless/no-TTY query() and reused
        # for interactive Sessions too, see claude_agent_sdk.py's docstring)
        # auto-approves every built-in tool, not just MCP tools. Restrict to
        # what Minty actually needs; no Edit/NotebookEdit, which nothing here
        # has a use for yet.
        #
        # Glob added while building research-discovery
        # (docs/research-discovery-plan.md §2's workspace-check step):
        # `ClaudeAgentOptions.tools` is a base allow-list, not just a
        # disallow-list on top of Claude Code's defaults (confirmed from
        # claude_agent_sdk's own types.py) — with only Read/Write allowed, no
        # session could ever list a directory (Read errors on one, same as
        # the outer Claude Code session's own Read tool) or resolve a
        # wildcard pattern. This was a latent gap already, not new:
        # morning-digest's own step 7 ("Glob the workspace's data/ for the
        # newest existing holdings_*.json") could never have actually
        # resolved without this — read-only, no write/execute surface, so it
        # doesn't touch the order-execution or Bash-removal (issue #25)
        # guardrail concerns at all.
        #
        # Skill added 2026-08-31, found live-testing research-discovery:
        # `ClaudeAgentOptions.tools` gates `Skill` itself, exactly like every
        # other built-in — `skills=[...]` (below) makes the SDK add "Skill"
        # to `allowed_tools` (permission auto-approval) automatically per its
        # own docstring, but that's a *different* field from `tools` (which
        # built-ins actually exist at all) and does not add it there. Without
        # this, `tools=["Read","Write","Glob"]` never made native Skill
        # invocation reachable at all — live A/B'd: the exact same
        # research-discovery-shaped prompt either got answered ad hoc (the
        # model just used india_macro/india_news directly) or got *described*
        # ("that's a job for the research-discovery skill...") without the
        # model ever actually invoking it, and only started working —
        # correctly asking its one clarifying question — once "Skill" was
        # added here. This affected every native (non-staged) skill, not
        # just research-discovery; staged skills were unaffected, since
        # `run_staged_<skill>` is a plain in-process MCP tool
        # (`staged_workflows` server), never gated by this allow-list at all.
        # A skill with a self-describing enough deterministic-script tool
        # name (e.g. red-flag-scan's `run_red_flag_check`) could sometimes
        # still produce a plausible-looking correct answer from tool names
        # alone without ever loading the real SKILL.md content — which is
        # exactly why this was never caught by unit tests (they exercise
        # `_build_options`'s wiring, not whether the model actually calls
        # Skill) and stayed invisible until a skill whose real value
        # (workspace check, structured planning, an exact hand-off filename)
        # isn't reconstructable from tool names alone made it visible.
        #
        # No Bash (issue #25, fixed 2026-08-27): every deterministic-script
        # tool already shells out server-side via engine/skill_tools.py's own
        # subprocess call, not the model's own Bash — so Bash was never
        # load-bearing for the designed skill flow. Its one real exercised
        # use (fetching a primary-source filing PDF directly) bypassed
        # mcp/common/nse_fetch.py's cache/throttle/circuit-breaker and
        # Minty's auto-capture/Sources-footer grounding entirely, with no
        # scoping ever actually enforced (`allowed_bash_prefixes` defaulted
        # to empty, making the scoping hook a permanent no-op — a prefix
        # allow-list can't reliably block network access anyway: curl,
        # `python -c` with urllib, wget, and nc all need different prefixes).
        # `india_filings.get_filing_document` is the governed replacement.
        # Same "structural, not policy" bar CLAUDE.md sets for order
        # execution — removing the tool closes the whole class at once.
        builtin_tools=builtin_tools if builtin_tools is not None else ["Read", "Write", "Glob", "Skill"],
        max_buffer_size=max_buffer_size if max_buffer_size is not None else _MAX_BUFFER_SIZE,
    )
