"""Raw, verbatim record of a `minty` REPL session — issue #13.

Audit/debug only ("what exactly did Minty tell me last Tuesday,"
reconstructing a prior conversation verbatim), not a compounding-research
mechanism — a raw transcript is exactly the kind of unstructured,
re-derivable content CLAUDE.md's notes guidance says not to save to
`workspace/notes.md`. Deliberately its own file, its own directory,
never routed through notes.md or any skill's `expected_outputs` — see
`docs/next-phase-plan.md` §8 for why the two are kept apart.

One file per REPL process (`engine/interactive.py`'s `_repl`), named by
the session's own start time so two sessions started back to back never
collide. Appended to turn by turn as the conversation happens, not
buffered and written once at exit, so a crash or Ctrl-C still leaves
whatever was actually said, not nothing. Never used by the headless
single-shot entrypoint (`engine/run.py`) — that path has no multi-turn
"session" to record, just one scripted call.

Already covered by the existing git-ignore/local-only rule for
`workspace/` (`docs/next-phase-plan.md` §4) — no new privacy surface,
same personal-financial-data sensitivity as everything else already
written there.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def new_transcript_path(workspace_root: Path, *, now: datetime | None = None) -> Path:
    """The one file this REPL process appends every turn to — filename
    fixed at session start, not re-derived per turn, so a long-running
    session doesn't fragment across midnight IST."""
    now = now or datetime.now(_IST)
    return workspace_root / "sessions" / f"{now.strftime('%Y-%m-%dT%H-%M-%S')}.md"


def append_turn(
    path: Path, prompt: str, response: str, *, speaker: str = "you", now: datetime | None = None
) -> None:
    """Appends one exchange. Creates the file (and its parent `sessions/`
    directory) with a one-time header on the first call for this path,
    appends bare turn blocks after that.

    `speaker` labels who the `prompt` half came from — "you" (default) for
    a real, human-typed turn. `engine/interactive.py`'s `_repl` passes
    "system" for its synthesized memory-candidate review turn, so the
    transcript doesn't misrepresent engine-authored text as something the
    user actually typed — this file's whole purpose is an accurate record
    of what was asked, and a bare "## you" header on a prompt nobody typed
    defeats that (found in review of issue #14).

    Every turn block carries its own full date, not just a time — a
    session left open across IST midnight would otherwise mislabel later
    turns under the header's start-of-session date, with nothing in the
    file to catch it (found in review of #13)."""
    now = now or datetime.now(_IST)
    timestamp = now.strftime("%Y-%m-%d %H:%M IST")
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    # Explicit, not the platform default: transcripts routinely carry ₹ and
    # Devanagari text, and the default encoding is locale-dependent, not
    # guaranteed UTF-8 on every platform (found in review of #13).
    with path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# Minty session — started {timestamp}\n\n")
        f.write(f"## {speaker} ({timestamp})\n\n{prompt}\n\n")
        f.write(f"## minty ({timestamp})\n\n{response}\n\n")


__all__ = ["append_turn", "new_transcript_path"]
