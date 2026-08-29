"""Tests for engine/diagnostics.py's `emit` — the gate between a routine
engine diagnostic and the terminal/log file (issue #37).
"""

from engine.diagnostics import emit
from engine.engine_log import new_engine_log_path


def test_emit_silent_on_terminal_by_default(monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)

    emit("[capture] rejected something")

    assert capsys.readouterr().out == ""


def test_emit_prints_when_minty_debug_is_set(monkeypatch, capsys):
    monkeypatch.setenv("MINTY_DEBUG", "1")

    emit("[capture] rejected something")

    assert "[capture] rejected something" in capsys.readouterr().out


def test_emit_accepts_true_and_yes_as_truthy(monkeypatch, capsys):
    for value in ("true", "True", "yes", "YES"):
        monkeypatch.setenv("MINTY_DEBUG", value)
        emit("diagnostic")
        assert "diagnostic" in capsys.readouterr().out


def test_emit_treats_empty_string_as_disabled(monkeypatch, capsys):
    monkeypatch.setenv("MINTY_DEBUG", "")

    emit("diagnostic")

    assert capsys.readouterr().out == ""


def test_emit_writes_to_log_path_regardless_of_debug_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)
    log_path = new_engine_log_path(tmp_path)

    emit("[capture] rejected something", log_path=log_path)

    assert capsys.readouterr().out == ""
    assert "[capture] rejected something" in log_path.read_text(encoding="utf-8")


def test_emit_is_a_noop_when_log_path_is_none_and_debug_is_off(monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)

    emit("diagnostic", log_path=None)

    assert capsys.readouterr().out == ""


def test_emit_survives_an_unwritable_log_path(monkeypatch, tmp_path):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)
    # A path whose parent can't be created (a file sitting where a
    # directory needs to go) — must not raise, this is a diagnostic-only
    # side effect (same convention as the transcript/audit write guards).
    blocker = tmp_path / "sessions"
    blocker.write_text("not a directory")
    log_path = blocker / "2026-08-25T14-32-10_engine.log"

    emit("diagnostic", log_path=log_path)
