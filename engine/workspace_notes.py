"""A typed SDK tool that guarantees "update the workspace's notes" always
lands at exactly `workspace_root/notes.md` — the single canonical path
docs/vision.md's workspace tier documents — instead of trusting the model
to invent the right filename itself.

Found live 2026-08-04 (compounding-proof test): with no existing notes.md
to imitate in a fresh workspace, the model improvised its own file
(`notes/open_decisions.md`) instead of the documented one. The content was
fine, and a later, genuinely separate session still found it by exploring
the workspace broadly — but relying on that exploration working every time
isn't the guarantee docs/vision.md's compounding claim needs. This tool
removes "which path" as a model decision, the same fix already applied to
the deterministic-script Bash-invocation problem in engine/skill_tools.py —
it doesn't decide *what* to write (the model still reads the current
content, merges, and composes the new text itself, per the Working Notes
convention's "read first, merge, don't overwrite" rule), only *where*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.workspace import WORKSPACES_ROOT

_WORKSPACE_ROOT_DESCRIPTION = (
    "Absolute path of the active workspace (as given to you in the "
    "'Active workspace:' note earlier in this turn)."
)

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
        "content": {
            "type": "string",
            "description": (
                "The full new content for the workspace's notes.md — read the "
                "current content first (via Read, if the file exists) and "
                "merge your update into it, don't just discard what's already "
                "there. This is the whole file's contents after your update, "
                "not a diff or an appended fragment."
            ),
        },
    },
    "required": ["workspace_root", "content"],
}


def _resolve_workspace_root(raw: str) -> Path | None:
    """None if `raw` doesn't resolve to a real directory inside
    WORKSPACES_ROOT. Same defensive check as engine/skill_tools.py's
    `_resolve_workspace_root`, duplicated rather than shared — the two
    tools' failure modes (a subprocess cwd vs. a write target) are
    different enough not to force a shared abstraction over yet."""
    try:
        resolved = Path(raw).resolve()
    except OSError:
        return None
    workspaces_root = WORKSPACES_ROOT.resolve()
    if workspaces_root not in resolved.parents and resolved != workspaces_root:
        return None
    if not resolved.is_dir():
        return None
    return resolved


async def _handler(args: dict[str, Any]) -> dict[str, Any]:
    workspace_root = _resolve_workspace_root(args.get("workspace_root", ""))
    if workspace_root is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"'workspace_root' must be an existing directory under "
                        f"{WORKSPACES_ROOT} — got {args.get('workspace_root')!r}"
                    ),
                }
            ],
            "is_error": True,
        }
    notes_path = workspace_root / "notes.md"
    notes_path.write_text(args["content"])
    return {"content": [{"type": "text", "text": f"wrote {notes_path}"}]}


def build_workspace_notes_tool() -> SdkMcpTool[Any]:
    return tool(
        "update_workspace_notes",
        "Save the workspace's persistent notebook — the only correct way to record "
        "an open thread, key finding, or reusable framework for this workspace. "
        "Always writes to workspace_root/notes.md, never a different filename or "
        "location — read the current content first with Read (if any), merge your "
        "update into it, then call this with the full merged content.",
        _INPUT_SCHEMA,
    )(_handler)


def build_workspace_notes_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="workspace_notes", tools=[build_workspace_notes_tool()])


__all__ = ["build_workspace_notes_server", "build_workspace_notes_tool"]
