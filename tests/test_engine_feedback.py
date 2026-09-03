"""Tests for engine/feedback.py — issue #73's local-only /feedback capture."""

from datetime import datetime

from engine.feedback import append_feedback, feedback_path
from engine.time_ist import IST as _IST


def test_append_feedback_creates_file_with_header_and_note(tmp_path):
    workspace_root = tmp_path / "workspace"

    path = append_feedback(
        workspace_root, "the login link wasn't clickable", now=datetime(2026, 9, 2, 18, 5, tzinfo=_IST)
    )

    assert path == workspace_root / "feedback.md"
    text = path.read_text()
    assert "Captured via `/feedback`" in text
    assert "nothing here is sent anywhere automatically" in text.lower()
    assert "the login link wasn't clickable" in text
    assert "## 2026-09-02 18:05 IST" in text


def test_append_feedback_appends_without_duplicating_the_header(tmp_path):
    workspace_root = tmp_path / "workspace"

    append_feedback(workspace_root, "first note", now=datetime(2026, 9, 2, 18, 5, tzinfo=_IST))
    append_feedback(workspace_root, "second note", now=datetime(2026, 9, 2, 18, 10, tzinfo=_IST))

    text = feedback_path(workspace_root).read_text()
    assert text.count("# Minty feedback") == 1
    assert "first note" in text
    assert "second note" in text
