"""Durable, structured per-tool-call audit log for a `minty` session —
issue #47.

None of Minty's structural guarantees (no order execution, identity-gated
holdings, scoped Bash — see `engine/guardrail.py`, `engine/kite_identity.py`,
`_build_bash_scope_hook` in `engine/harnesses/claude_agent_sdk.py`) leave
any durable trace that they actually fired correctly over the life of a
session — only the enforcing code exists, not a record that it ran as
intended. `engine/session_transcript.py` records the human-readable
prompt/response prose, but never a tool's name, arguments, or result.

Modeled directly on `session_transcript.py`: one JSONL file per session,
named by the session's own start time, appended to turn by turn rather
than buffered and written once at exit, so a crash or Ctrl-C still leaves
whatever tool calls actually happened. Deliberately its own file, next to
(not inside) the human transcript, so a machine can `jq` over it without
parsing markdown.

Records are built by `engine/harnesses/claude_agent_sdk.py`'s
`ClaudeSession.send()` from the same streamed `ToolUseBlock`/
`ToolResultBlock` pairs it already walks for auto-capture — see that
module for how `last_tool_calls` is populated. This module only owns the
file format and the append.

Never carries a full tool result — see `save_tool_result`
(`engine/tool_capture.py`) and `CAPTURE_SPECS` for where the real payload
already goes for the tools that matter. Re-logging a full payload here
would reintroduce exactly the problem issue #46 fixed (a single tool
result exceeding what should ever be held in memory/passed around
uncontrolled) for every tool, not just holdings.

Already covered by the existing git-ignore/local-only rule for
`workspace/` — no new privacy surface.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.time_ist import now_ist


def new_audit_log_path(workspace_root: Path, *, now: datetime | None = None) -> Path:
    """Named identically to `session_transcript.new_transcript_path`'s own
    scheme, same `sessions/` directory — the two files for one session sit
    side by side and are trivially correlatable by name. Callers that also
    call `new_transcript_path` for the same session should pass the same
    `now` to both, so the pair shares an exact timestamp rather than two
    independent `datetime.now()` calls landing a second apart."""
    now = now or now_ist()
    return workspace_root / "sessions" / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_tool_calls.jsonl"


def append_tool_calls(path: Path, records: list[dict[str, Any]], *, now: datetime | None = None) -> None:
    """Appends one JSON object per line, each stamped with a wall-clock
    timestamp. Creates `path`'s parent `sessions/` directory on first use,
    same as `session_transcript.append_turn`. A no-op if `records` is
    empty — a turn with no tool calls at all shouldn't create an empty
    file."""
    if not records:
        return
    now = now or now_ist()
    timestamp = now.strftime("%Y-%m-%d %H:%M IST")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            line = {"timestamp": timestamp, **record}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


__all__ = ["append_tool_calls", "new_audit_log_path"]
