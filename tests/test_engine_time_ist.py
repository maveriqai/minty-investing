"""Tests for engine/time_ist.py — the single source of truth for IST
timezone/date handling across engine/ (issue #22), replacing seven
independent `_IST = ZoneInfo("Asia/Kolkata")` definitions.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.time_ist import IST, now_ist, today_ist


def test_ist_is_asia_kolkata():
    assert IST == ZoneInfo("Asia/Kolkata")


def test_now_ist_returns_an_aware_datetime_in_ist():
    now = now_ist()

    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now(IST).utcoffset()


def test_today_ist_returns_todays_date_in_ist_as_iso_string():
    assert today_ist() == now_ist().date().isoformat()
