"""A typed SDK tool that guarantees "update the workspace's notes" always
lands at one of a small, allow-listed set of canonical paths — instead of
trusting the model to invent the right filename itself.

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

`target` defaults to `notes.md` — the one file most skills ever write —
and also accepts `theses/<SYMBOL>.md` (docs/next-phase-plan.md §4: the one
skill whose content is a living, per-symbol document, not workspace-wide
notes, so each symbol gets its own file rather than sharing one growing
notes.md). Still a small, fixed set the model chooses *from*, not an
arbitrary path it invents.
"""

from __future__ import annotations

import re
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root

_TARGET_DESCRIPTION = (
    "Which file to update — 'notes.md' (the default; the workspace's general "
    "notebook) or 'theses/<SYMBOL>.md' (a specific stock's thesis file, "
    "SYMBOL uppercase, e.g. 'theses/RELIANCE.md'). No other path is accepted."
)

_THESIS_TARGET_RE = re.compile(r"^theses/[A-Z0-9&\-]+\.md$")

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
        "target": {"type": "string", "description": _TARGET_DESCRIPTION, "default": "notes.md"},
        "content": {
            "type": "string",
            "description": (
                "The full new content for the target file — read the current "
                "content first (via Read, if the file exists) and merge your "
                "update into it, don't just discard what's already there. "
                "This is the whole file's contents after your update, not a "
                "diff or an appended fragment."
            ),
        },
    },
    "required": ["workspace_root", "content"],
}


def _resolve_target(raw: str) -> str | None:
    """None if `raw` isn't in the allow-listed set — 'notes.md' or
    'theses/<SYMBOL>.md'."""
    if raw == "notes.md":
        return raw
    if _THESIS_TARGET_RE.match(raw):
        return raw
    return None


async def _handler(args: dict[str, Any]) -> dict[str, Any]:
    workspace_root = _resolve_workspace_root(args.get("workspace_root", ""))
    if workspace_root is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"'workspace_root' must be an existing workspace directory — got {args.get('workspace_root')!r}",
                }
            ],
            "is_error": True,
        }
    target = _resolve_target(args.get("target") or "notes.md")
    if target is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"'target' must be 'notes.md' or 'theses/<SYMBOL>.md' — got {args.get('target')!r}"
                    ),
                }
            ],
            "is_error": True,
        }
    target_path = workspace_root / target
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(args["content"])
    return {"content": [{"type": "text", "text": f"wrote {target_path}"}]}


def build_workspace_notes_tool() -> SdkMcpTool[Any]:
    return tool(
        "update_workspace_notes",
        "Save the workspace's persistent notebook — the only correct way to record "
        "an open thread, key finding, or reusable framework for this workspace, or "
        "to update a specific stock's thesis file. Always writes to workspace_root "
        "plus an allow-listed target (notes.md by default, or theses/<SYMBOL>.md), "
        "never an invented filename or location — read the current content first "
        "with Read (if any), merge your update into it, then call this with the "
        "full merged content.",
        _INPUT_SCHEMA,
    )(_handler)


def build_workspace_notes_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="workspace_notes", tools=[build_workspace_notes_tool()])


__all__ = ["build_workspace_notes_server", "build_workspace_notes_tool"]
