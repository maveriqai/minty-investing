"""A typed SDK tool that turns a reviewed `/feedback` draft into a real
GitHub issue on maveriqai/minty-investing — issue #73's redesign.

Only ever meant to be called at the end of the review flow
`engine/feedback.py`'s `build_feedback_review_prompt` sets up (see
`engine/interactive.py`'s `/feedback` dispatch): the model has already
shown the user the exact title/body and gotten an explicit "share with the
team?" answer before this tool is invoked — see
`_FEEDBACK_ISSUE_SYSTEM_PROMPT` (engine/harnesses/claude_agent_sdk.py) for
the instruction enforcing that, and CLAUDE.md's "Model-initiated writes"
section for why that gate is prompt-engineered, not code-enforced — the
same accepted limitation issue #23 already documents for the
memory-candidate pipeline. Nothing here re-derives that trust boundary in
code; the one code-enforced gate in this redesign is the native "may I even
look at the transcript?" confirm in `engine/interactive.py`, upstream of
this tool entirely.

`share=False` never touches the network — it's how a declined report still
gets its enhanced/redacted draft saved locally (`append_feedback_report`),
distinct from the raw note `append_feedback` already wrote as a safety net
the moment analysis was agreed to. `share=True` shells out to `gh issue
create` with a fixed argv list (mirroring engine/skill_tools.py's
subprocess pattern) — never `shell=True`, title/body passed as separate
argv elements, never string-interpolated into a command string. `gh` not
being installed or authenticated is an expected, handled outcome, not an
engine fault: on any failure (missing binary, non-zero exit, timeout), the
local entry gets the exact `gh issue create ...` command as a fallback for
the user to run by hand instead of an issue URL, and the tool reports
success (`is_error` left unset/False) since it did everything deterministic
it could — surfacing it as a tool error would misrepresent an expected,
already-handled case as something that broke.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server, tool

from engine.feedback import append_feedback_report
from engine.workspace import WORKSPACE_ROOT_ARG_DESCRIPTION as _WORKSPACE_ROOT_DESCRIPTION
from engine.workspace import resolve_workspace_root_arg as _resolve_workspace_root

_FEEDBACK_REPO = "maveriqai/minty-investing"
_GH_TIMEOUT_S = 30.0

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "workspace_root": {"type": "string", "description": _WORKSPACE_ROOT_DESCRIPTION},
        "title": {
            "type": "string",
            "description": "The exact issue title you already showed the user for review.",
        },
        "body": {
            "type": "string",
            "description": "The exact issue body (evidence, redacted) you already showed the user for review.",
        },
        "share": {
            "type": "boolean",
            "description": (
                "True only if the user just gave an explicit yes, in this conversation, to "
                "sharing this specific report with the Minty team as a real GitHub issue. False "
                "otherwise — the report is still saved locally either way."
            ),
        },
    },
    "required": ["workspace_root", "title", "body", "share"],
}


def _fallback_command(title: str, body: str) -> str:
    return f"gh issue create --repo {_FEEDBACK_REPO} --title {shlex.quote(title)} --body {shlex.quote(body)}"


async def _run_gh_issue_create(title: str, body: str) -> tuple[bool, str, str]:
    """Never raises — every failure mode (`gh` missing, non-zero exit,
    timeout) comes back as `(False, "", reason)` so the caller can fall
    back to a runnable command instead of surfacing a tool error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "issue",
            "create",
            "--repo",
            _FEEDBACK_REPO,
            "--title",
            title,
            "--body",
            body,
            # Never let an unauthenticated `gh` block on an interactive
            # re-auth/browser prompt — a hung subprocess could otherwise sit
            # past even the timeout below on some `gh` versions.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return False, "", str(exc)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GH_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return False, "", f"gh issue create timed out after {_GH_TIMEOUT_S:.0f}s"
    if proc.returncode != 0:
        reason = stderr.decode().strip() or stdout.decode().strip() or f"exited {proc.returncode}"
        return False, "", reason
    return True, stdout.decode().strip(), ""


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
    title = args["title"]
    body = args["body"]
    if not args.get("share"):
        append_feedback_report(workspace_root, title=title, body=body)
        return {"content": [{"type": "text", "text": "Saved locally — not shared with the Minty team."}]}
    ok, issue_url, error = await _run_gh_issue_create(title, body)
    if ok:
        append_feedback_report(workspace_root, title=title, body=body, issue_url=issue_url)
        return {"content": [{"type": "text", "text": f"Filed: {issue_url}"}]}
    fallback = _fallback_command(title, body)
    append_feedback_report(workspace_root, title=title, body=body, fallback_command=fallback)
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Couldn't file it automatically ({error}) — saved locally instead. Run this "
                    f"yourself to share it:\n\n{fallback}"
                ),
            }
        ]
    }


def build_feedback_issue_tool() -> SdkMcpTool[Any]:
    return tool(
        "file_feedback_issue",
        "Save a reviewed /feedback report locally, and — only when share=True — file it as a real "
        "GitHub issue on maveriqai/minty-investing via `gh issue create`. Only call this as the "
        "last step of an explicit /feedback review flow, after showing the user the exact "
        "title/body and getting their explicit answer on whether to share it; never speculatively "
        "or on your own initiative. Call it exactly once per report, with share=True only "
        "immediately after an explicit yes in this conversation.",
        _INPUT_SCHEMA,
    )(_handler)


def build_feedback_issue_server() -> McpSdkServerConfig:
    return create_sdk_mcp_server(name="feedback_issue", tools=[build_feedback_issue_tool()])


__all__ = ["build_feedback_issue_server", "build_feedback_issue_tool"]
