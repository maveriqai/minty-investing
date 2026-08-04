"""Platform-abstraction seam for the morning-digest reminder (docs/vision.md
§2: "a lightweight scheduled OS notification (no agent involved) nudges the
user each morning" — a plain OS-level popup, never the engine itself
calling Claude). Mirrors the Harness seam's own build-the-seam-now,
implement-what's-needed pattern (engine/harnesses/base.py): one interface,
one backend per OS, selected at runtime by `sys.platform`.

Only Mon-Fri fires. Equities don't trade on weekends, and morning-digest
itself already handles a closed market gracefully (its own step 2), so a
weekend reminder would just be noise — not worth the extra
exchange-holiday-calendar dependency this module would otherwise need to
also skip market holidays; "weekday" is a good enough approximation for a
nudge, not a hard requirement.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol

DEFAULT_TIME = "08:30"
DEFAULT_MESSAGE = "Time for your Minty morning digest — open a terminal and ask for it."
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


@dataclass(frozen=True)
class ReminderStatus:
    installed: bool
    detail: str


class ReminderBackend(Protocol):
    def install(self, time: str = DEFAULT_TIME, message: str = DEFAULT_MESSAGE) -> None: ...
    def uninstall(self) -> None: ...
    def status(self) -> ReminderStatus: ...


def select_backend() -> ReminderBackend:
    """Raises for any platform without a backend yet, rather than silently
    no-op'ing — a user on an unsupported platform should get a clear answer,
    not a reminder that was silently never actually scheduled."""
    if sys.platform == "darwin":
        from engine.reminder.macos import MacOSReminderBackend

        return MacOSReminderBackend()
    if sys.platform in ("win32", "cygwin"):
        from engine.reminder.windows import WindowsReminderBackend

        return WindowsReminderBackend()
    raise NotImplementedError(
        f"No reminder backend for platform {sys.platform!r} yet — only macOS and Windows are supported."
    )


def parse_time(time: str) -> tuple[int, int]:
    """"08:30" -> (8, 30). Deliberately strict (raises ValueError on
    anything else) — a silently misparsed time would install a reminder
    that fires at the wrong hour with no visible error."""
    hour_str, sep, minute_str = time.partition(":")
    if not sep:
        raise ValueError(f"time must be HH:MM, got {time!r}")
    try:
        hour, minute = int(hour_str), int(minute_str)
    except ValueError:
        raise ValueError(f"time must be HH:MM with integer hour/minute, got {time!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time must be a valid 24h HH:MM, got {time!r}")
    return hour, minute


__all__ = [
    "DEFAULT_MESSAGE",
    "DEFAULT_TIME",
    "WEEKDAYS",
    "ReminderBackend",
    "ReminderStatus",
    "parse_time",
    "select_backend",
]
