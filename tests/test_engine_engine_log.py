"""Tests for engine/engine_log.py — the durable, plain-text home for the
engine's routine diagnostics (issue #37). Modeled on
tests/test_engine_tool_audit.py.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.engine_log import append_engine_log, new_engine_log_path

_IST = ZoneInfo("Asia/Kolkata")


def test_new_engine_log_path_is_named_by_session_start_time(tmp_path):
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)

    path = new_engine_log_path(tmp_path, now=now)

    assert path == tmp_path / "sessions" / "2026-08-25T14-32-10_engine.log"


def test_append_engine_log_creates_sessions_dir_and_writes_one_line_per_entry(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_engine.log"
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)

    append_engine_log(path, ["[budget] india_news.get_news ran 27/25 times", "[no files changed this turn]"], now=now)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0] == "[2026-08-25 14:32 IST] [budget] india_news.get_news ran 27/25 times"
    assert lines[1] == "[2026-08-25 14:32 IST] [no files changed this turn]"


def test_append_engine_log_appends_across_calls_without_clobbering(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_engine.log"
    first_call = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)
    second_call = datetime(2026, 8, 25, 14, 35, 0, tzinfo=_IST)

    append_engine_log(path, ["first"], now=first_call)
    append_engine_log(path, ["second"], now=second_call)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("first")
    assert lines[1].endswith("second")


def test_append_engine_log_is_a_noop_on_an_empty_list(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_engine.log"

    append_engine_log(path, [])

    assert not path.exists()


def test_append_engine_log_writes_non_ascii_content_as_utf8(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_engine.log"
    now = datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST)

    append_engine_log(path, ["आपके पास ₹1,234 cr है।"], now=now)

    text = path.read_text(encoding="utf-8")
    assert "₹" in text
    assert "आपके पास ₹1,234 cr है।" in text
