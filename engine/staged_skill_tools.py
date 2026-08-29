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

from typing import Any

from claude_agent_sdk import (
    McpSdkServerConfig,
    SdkMcpTool,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from engine import skills, staged_skills
from engine.harnesses.base import ToolConfig
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
