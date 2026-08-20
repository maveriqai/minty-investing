"""Turns each skill's declared `deterministic_scripts` (see engine/skills.py)
into typed, per-skill SDK tools — so "run the deterministic scan" is a real
tool call the model makes with named arguments, not a multi-line Bash
command it has to remember correctly from SKILL.md prose.

Built after live-testing showed the actual adherence gap wasn't the
scripts themselves — every ported script already computes *and* writes its
own output file (`out_path.write_text(...)` inside the script, see
red_flag_check.py / health_check.py / etc.) — it was the model forgetting
to invoke Bash at all, or mistyping the command. A typed tool call is a
much more reliable thing for a tool-calling model to get right than a
hand-assembled shell command from memory.

Deliberately not per-skill engine code: one generic tool *factory* reads
whatever each skill declares in its own SKILL.md frontmatter and builds the
tool from that — adding a new skill's deterministic step costs a
frontmatter entry, not a new function here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.skills import SKILLS_ROOT, load_deterministic_scripts
from engine.workspace import WORKSPACE_ROOT, is_within_known_workspace_roots

_WORKSPACE_ROOT_PARAM = "workspace_root"
_WORKSPACE_ROOT_DESCRIPTION = (
    "Absolute path of the active workspace (as given to you in the "
    "'Active workspace:' note earlier in this turn). The script runs with "
    "this as its working directory, so its output lands in the right "
    "workspace's results/."
)


def _json_schema_for_script(script_spec: dict) -> dict[str, Any]:
    """Builds a full JSON Schema (not the SDK's dict-shorthand, which marks
    every key required) so optional args stay genuinely optional."""
    properties: dict[str, Any] = {
        _WORKSPACE_ROOT_PARAM: {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION}
    }
    required = [_WORKSPACE_ROOT_PARAM]
    for arg in script_spec.get("args", []):
        properties[arg["name"]] = {
            "type": "string",
            "description": arg.get("description") or arg["name"],
        }
        if arg.get("required"):
            required.append(arg["name"])
    return {"type": "object", "properties": properties, "required": required}


def _build_argv(script_spec: dict, args: dict[str, str]) -> list[str]:
    """Positional args in declared order, then flag args as `--flag value`
    — no ported script mixes both kinds, so relative order between the two
    groups doesn't matter in practice."""
    argv: list[str] = []
    for arg in script_spec.get("args", []):
        value = args.get(arg["name"])
        if value is None:
            continue
        if arg["kind"] == "positional":
            argv.append(value)
        elif arg["kind"] == "flag":
            argv.extend([arg["flag"], value])
        else:
            raise ValueError(f"unknown arg kind {arg['kind']!r} for {arg['name']!r}")
    return argv


def _missing_required_args(script_spec: dict, args: dict[str, str]) -> list[str]:
    return [
        arg["name"]
        for arg in script_spec.get("args", [])
        if arg.get("required") and not args.get(arg["name"])
    ]


def _resolve_workspace_root(raw: str) -> Path | None:
    """None if `raw` doesn't resolve to a real directory inside a known
    workspace root — defense in depth against a model-supplied path
    escaping the workspace tree, since this becomes a subprocess cwd."""
    try:
        resolved = Path(raw).resolve()
    except OSError:
        return None
    if not is_within_known_workspace_roots(resolved):
        return None
    if not resolved.is_dir():
        return None
    return resolved


async def _run_script(script_path: Path, argv: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        str(script_path),
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


def _make_tool(skill_name: str, script_spec: dict) -> SdkMcpTool[Any]:
    script_path = (SKILLS_ROOT / skill_name / script_spec["path"]).resolve()
    tool_name = f"run_{script_spec['id']}"

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        missing = _missing_required_args(script_spec, args)
        if missing:
            return {
                "content": [{"type": "text", "text": f"Missing required argument(s): {', '.join(missing)}"}],
                "is_error": True,
            }
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
        argv = _build_argv(script_spec, args)
        returncode, stdout, stderr = await _run_script(script_path, argv, workspace_root)
        if returncode != 0:
            return {
                "content": [{"type": "text", "text": f"{script_spec['id']} exited {returncode}:\n{stderr or stdout}"}],
                "is_error": True,
            }
        return {"content": [{"type": "text", "text": stdout}]}

    return tool(
        tool_name,
        f"Run {skill_name}'s {script_spec['id']} deterministic script and save its output — "
        f"the only correct way to compute this skill's numbers, never by hand.",
        _json_schema_for_script(script_spec),
    )(handler)


def build_skill_tools(skill_names: list[str]) -> list[SdkMcpTool[Any]]:
    """One typed tool per deterministic script declared across `skill_names`
    — empty if none declare any (an undeclared skill just contributes no
    tools, not an error)."""
    tools: list[SdkMcpTool[Any]] = []
    for skill_name in skill_names:
        for script_spec in load_deterministic_scripts(skill_name):
            tools.append(_make_tool(skill_name, script_spec))
    return tools


def build_skill_tools_server(skill_names: list[str]) -> McpSdkServerConfig | None:
    """None if no loaded skill declares any deterministic script — avoids
    registering an empty, pointless in-process server."""
    tools = build_skill_tools(skill_names)
    if not tools:
        return None
    return create_sdk_mcp_server(name="skill_scripts", tools=tools)


__all__ = ["build_skill_tools", "build_skill_tools_server"]
