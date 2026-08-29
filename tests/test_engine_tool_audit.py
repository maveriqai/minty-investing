"""Tests for engine/tool_audit.py — the durable, structured per-tool-call
audit log (issue #47). Modeled on tests/test_engine_session_transcript.py.
"""

import json
from datetime import datetime

from engine.time_ist import IST as _IST
from engine.tool_audit import append_tool_calls, new_audit_log_path


def test_new_audit_log_path_is_named_by_session_start_time(tmp_path):
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)

    path = new_audit_log_path(tmp_path, now=now)

    assert path == tmp_path / "sessions" / "2026-08-25T14-32-10_tool_calls.jsonl"


def test_append_tool_calls_creates_sessions_dir_and_writes_one_line_per_record(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_tool_calls.jsonl"
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)
    records = [
        {"tool_use_id": "t1", "tool_name": "mcp__india_price__get_quote", "status": "completed"},
        {"tool_use_id": "t2", "tool_name": "mcp__kite_gateway__get_holdings", "status": "error"},
    ]

    append_tool_calls(path, records, now=now)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool_use_id"] == "t1"
    assert first["status"] == "completed"
    assert first["timestamp"] == "2026-08-25 14:32 IST"
    second = json.loads(lines[1])
    assert second["tool_use_id"] == "t2"
    assert second["status"] == "error"


def test_append_tool_calls_appends_across_calls_without_clobbering(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_tool_calls.jsonl"
    first_call = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)
    second_call = datetime(2026, 8, 25, 14, 35, 0, tzinfo=_IST)

    append_tool_calls(path, [{"tool_use_id": "t1", "status": "completed"}], now=first_call)
    append_tool_calls(path, [{"tool_use_id": "t2", "status": "completed"}], now=second_call)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["tool_use_id"] == "t1"
    assert json.loads(lines[1])["tool_use_id"] == "t2"


def test_append_tool_calls_is_a_noop_on_an_empty_list(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_tool_calls.jsonl"

    append_tool_calls(path, [])

    assert not path.exists()


def test_append_tool_calls_writes_non_ascii_content_as_utf8(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10_tool_calls.jsonl"
    now = datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST)
    records = [{"tool_use_id": "t1", "result_preview": "आपके पास ₹1,234 cr है।"}]

    append_tool_calls(path, records, now=now)

    text = path.read_text(encoding="utf-8")
    assert "₹" in text
    assert json.loads(text.strip())["result_preview"] == "आपके पास ₹1,234 cr है।"
