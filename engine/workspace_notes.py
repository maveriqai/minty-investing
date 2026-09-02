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

Extended (docs/research-discovery-plan.md §6) with four more patterns for
the research-discovery skills: `research/sectors/<slug>.md`,
`research/stocks/<SYMBOL>.md`, `research/themes/<slug>.md` — one file per
subject, keyed the same way `theses/<SYMBOL>.md` already is, per
docs/research-notes-design.md §2.1/§2.2 — and
`data/research_plan_<slug>_<date>.json`, the plan-file handoff between
`research-discovery` (writes it) and `research-discovery-gather` (reads
it via its `dynamic: true` stage, see engine/staged_skills.py) — the
pragmatic native substitute for a real pause/resume primitive, decided
after confirming (engine/staged_skill_tools.py) that a staged run can
neither pause for the user nor receive per-invocation content.

Extended again (issue #61) with `data/research_finding_<angle_id>_<date>.json`
— each `gather` instance's own output, the counterpart to the plan-file
handoff above. This one was missing outright, not just undocumented:
`_expand_dynamic_stage` (engine/staged_skills.py) generates a per-angle
instruction telling the model to save this file, and until issue #55
(2026-09-01) removed the raw `Write` tool from `builtin_tools`, that
instruction meant a literal `Write` call, which needed no entry here at
all. #55's own audit (grepping every `.claude/skills/*/SKILL.md` for a
live `Write` use) never saw this call, since the instruction text is
generated in this Python module, not in any SKILL.md — so removing `Write`
silently broke every `gather` instance's ability to persist its finding,
live-reproduced 2026-09-02 (a rejected update_workspace_notes call, target
`data/research_finding_fed-policy-outlook_2026-09-02.json`, `_RESEARCH_PLAN_RE`
matching only `research_plan`, never `research_finding`).
"""

from __future__ import annotations

import re
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root

_TARGET_DESCRIPTION = (
    "Which file to update — 'notes.md' (the default; the workspace's general "
    "notebook), 'theses/<SYMBOL>.md' (a specific stock's thesis file, SYMBOL "
    "uppercase, e.g. 'theses/RELIANCE.md'), 'research/sectors/<slug>.md', "
    "'research/stocks/<SYMBOL>.md', or 'research/themes/<slug>.md' (a "
    "research-discovery finding, keyed by which bucket it belongs in — slug "
    "lowercase-hyphenated, e.g. 'research/sectors/automobile-and-auto-"
    "components.md'), 'data/research_plan_<slug>_<date>.json' "
    "(research-discovery's own handoff file to research-discovery-gather, "
    "date as YYYY-MM-DD), or 'data/research_finding_<angle_id>_<date>.json' "
    "(a research-discovery-gather angle's own finding, angle_id "
    "lowercase-hyphenated, date as YYYY-MM-DD). No other path is accepted."
)

_THESIS_TARGET_RE = re.compile(r"^theses/[A-Z0-9&\-]+\.md$")
_SECTOR_RESEARCH_RE = re.compile(r"^research/sectors/[a-z0-9]+(-[a-z0-9]+)*\.md$")
_STOCK_RESEARCH_RE = re.compile(r"^research/stocks/[A-Z0-9&\-]+\.md$")
_THEME_RESEARCH_RE = re.compile(r"^research/themes/[a-z0-9]+(-[a-z0-9]+)*\.md$")
_RESEARCH_PLAN_RE = re.compile(r"^data/research_plan_[a-z0-9]+(-[a-z0-9]+)*_\d{4}-\d{2}-\d{2}\.json$")
_RESEARCH_FINDING_RE = re.compile(r"^data/research_finding_[a-z0-9]+(-[a-z0-9]+)*_\d{4}-\d{2}-\d{2}\.json$")

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
    """None if `raw` isn't in the allow-listed set — 'notes.md',
    'theses/<SYMBOL>.md', one of the three 'research/<bucket>/<key>.md'
    forms, 'data/research_plan_<slug>_<date>.json', or
    'data/research_finding_<angle_id>_<date>.json'."""
    if raw == "notes.md":
        return raw
    for pattern in (
        _THESIS_TARGET_RE,
        _SECTOR_RESEARCH_RE,
        _STOCK_RESEARCH_RE,
        _THEME_RESEARCH_RE,
        _RESEARCH_PLAN_RE,
        _RESEARCH_FINDING_RE,
    ):
        if pattern.match(raw):
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
                        "'target' must be 'notes.md', 'theses/<SYMBOL>.md', "
                        "'research/sectors|stocks|themes/<key>.md', "
                        "'data/research_plan_<slug>_<date>.json', or "
                        f"'data/research_finding_<angle_id>_<date>.json' — got {args.get('target')!r}"
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
        "an open thread, key finding, or reusable framework for this workspace, to "
        "update a specific stock's thesis file, to file a research-discovery finding "
        "into its sector/stock/theme bucket, to hand off a research-discovery plan "
        "to research-discovery-gather, or to save a single gather angle's own "
        "finding. Always writes to workspace_root plus an allow-listed target "
        "(notes.md by default, theses/<SYMBOL>.md, "
        "research/sectors|stocks|themes/<key>.md, data/research_plan_<slug>_"
        "<date>.json, or data/research_finding_<angle_id>_<date>.json), never an "
        "invented filename or location — read the current content first with Read "
        "(if any), merge your update into it, then call this with the full merged "
        "content.",
        _INPUT_SCHEMA,
    )(_handler)


def build_workspace_notes_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="workspace_notes", tools=[build_workspace_notes_tool()])


__all__ = ["build_workspace_notes_server", "build_workspace_notes_tool"]
