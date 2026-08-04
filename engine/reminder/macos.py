"""launchd-backed reminder backend — installs a LaunchAgent that fires a
notification Mon-Fri at a configured local time. No agent, no Python
process is involved in the actual firing — launchd and the notifier are
both plain OS-level components, matching docs/vision.md §2's "no agent
involved" requirement exactly.

**Notifier choice, and why it isn't plain `osascript -e 'display
notification'`.** That was the first implementation, live-verified
2026-08-04 — the notification itself worked, but clicking it opened
*Script Editor* instead of doing anything useful. This is a known,
long-documented macOS quirk, not a bug in this module: a notification
posted via the bare `osascript` binary gets attributed to Script Editor's
own identity in Notification Center, so a click can bring Script Editor
forward — there's no supported way to override this from plain
`osascript`. `terminal-notifier` exists specifically to fix this (its own
README cites this exact issue as the reason it was built): it ships its
own small helper so notifications get a proper identity and a real click
action. This module now prefers `terminal-notifier` when it's on PATH —
detected via `shutil.which`, not assumed — wiring its `-execute` flag to
open a Terminal window at the repo root on click (not to run
`engine.interactive` automatically; starting the actual conversation
stays a deliberate action the user takes once the terminal is open, same
"manual trigger" boundary docs/vision.md §2 draws for the digest itself).
Falls back to the original plain-`osascript` behavior when
`terminal-notifier` isn't installed — degraded (the Script Editor
click quirk returns), not broken.

Live-verified 2026-08-04, both paths: the original osascript-only
notification (fired and confirmed via `launchctl list`); after switching
to `terminal-notifier` (installed via Homebrew), the plist/helper-script
construction and a real install→status→uninstall round-trip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from engine.reminder.base import DEFAULT_MESSAGE, DEFAULT_TIME, ReminderStatus, parse_time
from engine.workspace import REPO_ROOT

LABEL = "com.maveriq.minty.reminder"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

_HELPER_DIR = Path.home() / "Library" / "Application Support" / "Minty"
OPEN_TERMINAL_SCRIPT = _HELPER_DIR / "reminder_open_terminal.sh"

# launchd's StartCalendarInterval Weekday field: 0 or 7 = Sunday, 1-6 = Mon-Sat.
_WEEKDAY_NUMBERS = (1, 2, 3, 4, 5)  # Mon-Fri


def _which_terminal_notifier() -> str | None:
    return shutil.which("terminal-notifier")


def _build_open_terminal_script(repo_root: Path) -> str:
    """A new Terminal window/tab cd'd into the repo — not auto-running
    `engine.interactive`, see module docstring's "no agent involved"
    note. The AppleScript source is single-quoted at the shell layer, so
    only the inner AppleScript string literal needs its own quotes
    escaped (backslash-doubled quote), not the shell layer."""
    escaped_path = str(repo_root).replace('"', '\\"')
    return f"""#!/bin/bash
osascript -e 'tell application "Terminal" to activate' -e 'tell application "Terminal" to do script "cd \\"{escaped_path}\\""'
"""


def _osascript_program_arguments(message: str) -> list[str]:
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    return [
        "/usr/bin/osascript",
        "-e",
        f'display notification "{escaped_message}" with title "Minty" subtitle "Morning digest"',
    ]


def _terminal_notifier_program_arguments(terminal_notifier_path: str, message: str) -> list[str]:
    return [
        terminal_notifier_path,
        "-title",
        "Minty",
        "-subtitle",
        "Morning digest",
        "-message",
        message,
        "-execute",
        f"/bin/bash '{OPEN_TERMINAL_SCRIPT}'",
    ]


def _build_plist(hour: int, minute: int, program_arguments: list[str]) -> str:
    intervals = "".join(
        f"""
        <dict>
            <key>Hour</key><integer>{hour}</integer>
            <key>Minute</key><integer>{minute}</integer>
            <key>Weekday</key><integer>{weekday}</integer>
        </dict>"""
        for weekday in _WEEKDAY_NUMBERS
    )
    args_xml = "".join(f"\n        <string>{_xml_escape(arg)}</string>" for arg in program_arguments)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>{args_xml}
    </array>
    <key>StartCalendarInterval</key>
    <array>{intervals}
    </array>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


class MacOSReminderBackend:
    def install(self, time: str = DEFAULT_TIME, message: str = DEFAULT_MESSAGE) -> None:
        hour, minute = parse_time(time)
        terminal_notifier_path = _which_terminal_notifier()
        if terminal_notifier_path is not None:
            OPEN_TERMINAL_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
            OPEN_TERMINAL_SCRIPT.write_text(_build_open_terminal_script(REPO_ROOT))
            OPEN_TERMINAL_SCRIPT.chmod(0o700)
            program_arguments = _terminal_notifier_program_arguments(terminal_notifier_path, message)
        else:
            program_arguments = _osascript_program_arguments(message)

        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(_build_plist(hour, minute, program_arguments))
        # Unload first, ignoring failure — idempotent reinstall: a stale
        # prior load (e.g. from an earlier `install()` call with a
        # different time) must not linger alongside the freshly written one.
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True, check=False)
        subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True, capture_output=True)

        if terminal_notifier_path is None:
            print(
                "Note: terminal-notifier isn't installed, so clicking the reminder won't do "
                "anything useful (a known macOS quirk misattributes plain osascript "
                "notifications to Script Editor). `brew install terminal-notifier` and "
                "reinstall the reminder to fix this."
            )

    def uninstall(self) -> None:
        if PLIST_PATH.exists():
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True, check=False)
            PLIST_PATH.unlink()
        if OPEN_TERMINAL_SCRIPT.exists():
            OPEN_TERMINAL_SCRIPT.unlink()

    def status(self) -> ReminderStatus:
        if not PLIST_PATH.exists():
            return ReminderStatus(installed=False, detail=f"no plist at {PLIST_PATH}")
        result = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True, check=False)
        loaded = result.returncode == 0
        detail = f"plist present at {PLIST_PATH}; " + (
            "loaded in launchd" if loaded else "NOT currently loaded in launchd — try reinstalling"
        )
        return ReminderStatus(installed=loaded, detail=detail)


__all__ = ["LABEL", "OPEN_TERMINAL_SCRIPT", "PLIST_PATH", "MacOSReminderBackend"]
