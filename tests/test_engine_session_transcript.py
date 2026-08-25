"""Tests for engine/session_transcript.py — the raw, verbatim per-turn
record of a `minty` REPL session (issue #13). Audit/debug mechanism only,
deliberately separate from notes.md's compounding-memory path.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.session_transcript import append_turn, new_transcript_path

_IST = ZoneInfo("Asia/Kolkata")


def test_new_transcript_path_is_named_by_session_start_time(tmp_path):
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)

    path = new_transcript_path(tmp_path, now=now)

    assert path == tmp_path / "sessions" / "2026-08-25T14-32-10.md"


def test_append_turn_creates_sessions_dir_and_writes_date_header_once(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10.md"
    now = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)

    append_turn(path, "what are my holdings?", "you hold RELIANCE.", now=now)

    text = path.read_text()
    assert text.startswith("# Minty session — 2026-08-25\n\n")
    assert text.count("# Minty session") == 1
    assert "## you (14:32 IST)" in text
    assert "what are my holdings?" in text
    assert "## minty (14:32 IST)" in text
    assert "you hold RELIANCE." in text


def test_append_turn_appends_a_second_turn_without_repeating_the_header(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10.md"
    first = datetime(2026, 8, 25, 14, 32, 10, tzinfo=_IST)
    second = datetime(2026, 8, 25, 14, 35, 0, tzinfo=_IST)

    append_turn(path, "first question", "first answer", now=first)
    append_turn(path, "second question", "second answer", now=second)

    text = path.read_text()
    assert text.count("# Minty session") == 1
    assert "first question" in text
    assert "second question" in text
    # Order preserved — a transcript reconstructed out of order defeats the
    # "what exactly did Minty tell me" use case this exists for.
    assert text.index("first question") < text.index("second question")


def test_append_turn_preserves_multiline_content_verbatim(tmp_path):
    path = tmp_path / "sessions" / "2026-08-25T14-32-10.md"
    response = "line one\nline two\n\n[Sources: workspace/data/holdings_2026-08-25.json]"

    append_turn(path, "multi\nline\nprompt", response, now=datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST))

    text = path.read_text()
    assert "multi\nline\nprompt" in text
    assert response in text
