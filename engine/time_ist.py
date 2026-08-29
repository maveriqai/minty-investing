"""Single source of truth for IST timezone/date handling across `engine/` —
`_IST = ZoneInfo("Asia/Kolkata")` used to be independently redefined in
seven separate modules (issue #22); this is the one place it's defined now.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> str:
    return now_ist().date().isoformat()


__all__ = ["IST", "now_ist", "today_ist"]
