"""Unit tests for engine/reminder/base.py's platform selection and time
parsing — the seam the mac/windows backends plug into.
"""

import pytest

from engine.reminder import base


def test_parse_time_accepts_valid_24h_time():
    assert base.parse_time("08:30") == (8, 30)
    assert base.parse_time("23:59") == (23, 59)
    assert base.parse_time("00:00") == (0, 0)


def test_parse_time_rejects_missing_colon():
    with pytest.raises(ValueError, match="HH:MM"):
        base.parse_time("0830")


def test_parse_time_rejects_out_of_range_hour_or_minute():
    with pytest.raises(ValueError):
        base.parse_time("24:00")
    with pytest.raises(ValueError):
        base.parse_time("08:60")


def test_parse_time_rejects_non_integer_components():
    with pytest.raises(ValueError, match="HH:MM"):
        base.parse_time("eight:30")


def test_select_backend_returns_macos_backend_on_darwin(monkeypatch):
    monkeypatch.setattr(base.sys, "platform", "darwin")
    backend = base.select_backend()
    assert type(backend).__name__ == "MacOSReminderBackend"


def test_select_backend_returns_windows_backend_on_win32(monkeypatch):
    monkeypatch.setattr(base.sys, "platform", "win32")
    backend = base.select_backend()
    assert type(backend).__name__ == "WindowsReminderBackend"


def test_select_backend_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(base.sys, "platform", "linux")
    with pytest.raises(NotImplementedError, match="linux"):
        base.select_backend()
