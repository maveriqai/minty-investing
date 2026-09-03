"""Local-only in-REPL feedback capture — issue #73.

Raised live during the 2026-09-02 v0.1.0 manual test: reporting a bug or
piece of feedback about Minty itself meant leaving the `minty` session
entirely to file a GitHub issue by hand. Scoped to the local-only version
the issue itself suggested first, given today's single-maintainer stage —
no GitHub/network call, no auth, just an append-only local file the user
(or the maintainer, later) can read and act on by hand. A `/feedback ...`
GitHub-integrated version, if ever wanted, is a separate, larger decision
(auth, rate limits, a broader user base) — not this.

Deliberately its own file, not routed through `notes.md` or any skill's
`expected_outputs` — this is feedback about Minty the tool, not a
durable investing finding, so it doesn't belong in the compounding-
research workspace content those exist for. Same "local, git-ignored"
guarantee as everything else under `workspace/` (docs/next-phase-plan.md
§4) — no new privacy surface.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from engine.time_ist import now_ist

# The REPL command a user types to capture feedback — checked as a prefix
# (engine/interactive.py's `_repl`), so `/feedback the login link wasn't
# clickable` both triggers it and supplies the note in one line.
FEEDBACK_COMMAND_PREFIX = "/feedback"


def feedback_path(workspace_root: Path) -> Path:
    return workspace_root / "feedback.md"


def append_feedback(workspace_root: Path, text: str, *, now: datetime | None = None) -> Path:
    """Appends one dated feedback note, creating the file (with a one-time
    header explaining what it is and that nothing in it is sent anywhere
    automatically) on the first call. Returns the path written, so the
    caller can tell the user exactly where to find it."""
    now = now or now_ist()
    timestamp = now.strftime("%Y-%m-%d %H:%M IST")
    path = feedback_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(
                "# Minty feedback\n\n"
                "Captured via `/feedback` in the REPL. Local only — nothing "
                "here is sent anywhere automatically; review it yourself and "
                "file what's worth filing as a GitHub issue.\n\n"
            )
        f.write(f"## {timestamp}\n\n{text}\n\n")
    return path


__all__ = ["FEEDBACK_COMMAND_PREFIX", "append_feedback", "feedback_path"]
