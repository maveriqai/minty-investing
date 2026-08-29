"""Durable home for the engine's own routine diagnostics — issue #37.

Modeled directly on `engine/session_transcript.py`/`engine/tool_audit.py`:
one plain-text file per session, named by the session's own start time, in
the same `sessions/` directory, appended to as the diagnostic happens
rather than buffered — a crash or Ctrl-C still leaves whatever was
actually logged.

Before this existed, lines like `[capture] rejected ...]` and
`[matches ...]` were plain, unconditional `print()`s with no durable
record at all — `engine/tool_capture.py`'s own docstring claimed they
"already land in `workspace/sessions/<timestamp>.md`," which was never
true (that file only ever records prompt/response text, never a stdout
diagnostic print — see `engine/session_transcript.py`). `engine/
diagnostics.py`'s `emit` is the module that actually decides where a
given diagnostic line goes (terminal, this file, or both); this module
only owns the file format and the append.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def new_engine_log_path(workspace_root: Path, *, now: datetime | None = None) -> Path:
    """Same `sessions/` directory, same timestamp format as
    `new_transcript_path`/`new_audit_log_path` — the three files for one
    session sit side by side and are trivially correlatable by name.
    Callers that also compute those two paths should pass the same `now`
    to all three, so they share one exact session timestamp."""
    now = now or datetime.now(_IST)
    return workspace_root / "sessions" / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}_engine.log"


def append_engine_log(path: Path, lines: list[str], *, now: datetime | None = None) -> None:
    """Appends one timestamped line per entry in `lines`. Creates `path`'s
    parent `sessions/` directory on first use. A no-op if `lines` is
    empty — a turn with nothing to log shouldn't create an empty file."""
    if not lines:
        return
    now = now or datetime.now(_IST)
    timestamp = now.strftime("%Y-%m-%d %H:%M IST")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"[{timestamp}] {line}\n")


__all__ = ["append_engine_log", "new_engine_log_path"]
