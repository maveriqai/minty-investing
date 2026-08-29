"""Turns each skill's declared `stages` (see `engine/skills.py`'s
`load_stages`) into one dedicated in-process SDK tool, `run_staged_<skill>`
— the routing mechanism decided in
docs/staged-skill-execution-design.md §8, candidate 3: the model calling
this tool *is* the routing decision, made the normal, already-reliable
way (tool selection by description), instead of intercepting or
predicting the model's native `Skill`-invocation.

Same "generic factory reads frontmatter, no per-skill engine code" shape
as `engine/skill_tools.py`. Registered on its own in-process server,
`staged_workflows`, separate from `skill_scripts` — a distinct namespace
in the model's own tool list, and a distinct `(server, tool)` category
that `engine/tool_capture.py`'s `parse_mcp_tool_name` and
`engine/tool_budget.py`'s `TurnBudgetTracker` can already key off if a
future need arises (§8, "Differentiating staged-workflow tools").

A staged skill must be built into *this* server only, never also left in
`tools.skills` for native Skill-invocation — see
`engine/harnesses/claude_agent_sdk.py`'s `_build_options`, which filters a
staged skill's name out of the native skill list for exactly this reason
(§8's first requirement: one entry point, no competing path for the model
to have to reliably prefer).
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import (
    McpSdkServerConfig,
    SdkMcpTool,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from engine import identity_check, skills, staged_skills
from engine.harnesses.base import ToolConfig
from engine.kite_identity import IdentityGuardState
from engine.skill_tools import (
    _WORKSPACE_ROOT_DESCRIPTION,
    _WORKSPACE_ROOT_PARAM,
    _resolve_workspace_root,
)
from engine.time_ist import today_ist
from engine.workspace import WORKSPACE_ROOT

STAGED_WORKFLOWS_SERVER_NAME = "staged_workflows"

_DESCRIPTION_SUFFIX = (
    " Multi-stage background workflow: runs several fresh internal "
    "sessions in sequence and returns one final result. Takes several "
    "minutes and makes many internal tool calls. Call this once for the "
    "whole run — don't call it repeatedly, and don't expect intermediate "
    "output back before it returns."
)


def _identity_mismatch_message(precheck: dict[str, Any]) -> str:
    """Mirrors the mismatch wording each staged skill's own SKILL.md
    already uses in its stage-1 identity-check step, so a user sees
    consistent phrasing whether the mismatch is caught here (issue #51,
    before any stage session opens) or inside a stage's own check."""
    return (
        "A different Zerodha account is connected than the one Minty has "
        f"on record — anchor account {precheck.get('anchor_user_id')!r}, "
        f"connected account {precheck.get('live_user_id')!r}. Minty is a "
        "single-account tool by design: this run was stopped before any "
        "stage opened, so nothing was fetched or overwritten. There's no "
        "tool call that resolves this — a human has to delete "
        "data/account_identity.json by hand if the connected account is "
        "now the correct one."
    )


def _make_staged_tool(skill_name: str, tools: ToolConfig) -> SdkMcpTool[Any]:
    # Deferred import: engine.harnesses.claude_agent_sdk imports this
    # module (to build the staged_workflows server), so a top-level import
    # here would be circular. By the time a tool handler actually runs,
    # that module has long since finished loading, so the deferred import
    # inside the handler resolves cleanly.
    from engine.harnesses.claude_agent_sdk import ClaudeAgentSDKHarness

    tool_name = f"run_staged_{skill_name.replace('-', '_')}"
    description = (skills.load_description(skill_name).strip() + _DESCRIPTION_SUFFIX).strip()
    skill_body = skills.load_skill_body(skill_name)
    stages = skills.load_stages(skill_name)
    identity_precheck = skills.load_identity_precheck(skill_name)

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        workspace_root = _resolve_workspace_root(args.get(_WORKSPACE_ROOT_PARAM, ""))
        if workspace_root is None:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{_WORKSPACE_ROOT_PARAM!r} must be an existing directory under "
                            f"{WORKSPACE_ROOT} — got {args.get(_WORKSPACE_ROOT_PARAM)!r}"
                        ),
                    }
                ],
                "is_error": True,
            }

        if identity_precheck:
            # Issue #51: catches a confirmed account mismatch before any
            # stage session opens — zero staged-run cost, deterministic,
            # no reliance on the model remembering to call this itself.
            # Calls the SdkMcpTool's own .handler directly — the exact
            # thing the model's own MCP round trip to check_identity_match
            # ultimately invokes — bypassing the MCP server/transport layer
            # entirely, same as how this file's own handler is itself
            # invoked directly in tests (built.handler({...})). Only
            # "mismatch" short-circuits: this handler is one atomic call
            # with no way to pause for user input, so "error" (e.g. no
            # active Kite session) and "no_anchor"/"match" all fall through
            # unchanged — stage 1 already has its own graceful fallback for
            # "no active session", and only a confirmed mismatch has no
            # such fallback and needs no user judgment call.
            precheck_tool = identity_check.build_identity_check_tool(IdentityGuardState())
            result = await precheck_tool.handler({})
            content = result.get("content") or []
            text = content[0]["text"] if content else ""
            precheck = json.loads(text) if not result.get("is_error") else {}
            if precheck.get("status") == "mismatch":
                return {"content": [{"type": "text", "text": _identity_mismatch_message(precheck)}]}

        harness = ClaudeAgentSDKHarness()
        final_text, all_captures = await staged_skills.run_staged_skill(
            harness, tools, skill_body, stages, workspace_root=workspace_root, date=today_ist()
        )
        full_text = staged_skills.compose_and_save(
            final_text, all_captures, skill_name=skill_name, workspace_root=workspace_root
        )
        return {"content": [{"type": "text", "text": full_text}]}

    return tool(
        tool_name,
        description,
        {
            "type": "object",
            "properties": {
                _WORKSPACE_ROOT_PARAM: {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION}
            },
            "required": [_WORKSPACE_ROOT_PARAM],
        },
        annotations=ToolAnnotations(
            title=f"Run staged {skill_name}",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )(handler)


def build_staged_workflow_tools_server(
    staged_skill_names: list[str], tools: ToolConfig
) -> McpSdkServerConfig | None:
    """None if `staged_skill_names` is empty — avoids registering an
    empty, pointless in-process server. Callers are expected to have
    already filtered to skills that actually declare `stages`."""
    built = [_make_staged_tool(name, tools) for name in staged_skill_names]
    if not built:
        return None
    return create_sdk_mcp_server(name=STAGED_WORKFLOWS_SERVER_NAME, tools=built)


__all__ = ["STAGED_WORKFLOWS_SERVER_NAME", "build_staged_workflow_tools_server"]
