"""Tests engine/claude_login.py's login-status logic against a fake
`subprocess.run`, independent of any real `claude` CLI install or session.
"""

import json
import subprocess

from engine import claude_login


class _FakeCompleted:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_is_logged_in_true_when_status_reports_logged_in(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(json.dumps({"loggedIn": True}))
    )
    assert claude_login.is_logged_in() is True


def test_is_logged_in_false_when_status_reports_logged_out(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(json.dumps({"loggedIn": False}))
    )
    assert claude_login.is_logged_in() is False


def test_is_logged_in_fails_open_on_malformed_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted("not json"))
    assert claude_login.is_logged_in() is True


def test_is_logged_in_fails_open_when_claude_binary_missing(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert claude_login.is_logged_in() is True


def test_ensure_logged_in_skips_login_flow_when_already_logged_in(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: (calls.append(cmd), _FakeCompleted(json.dumps({"loggedIn": True})))[1],
    )
    assert claude_login.ensure_logged_in() is True
    assert calls == [["claude", "auth", "status", "--json"]]


def test_ensure_logged_in_runs_login_then_rechecks(monkeypatch):
    calls = []

    def _fake_run(cmd, **k):
        calls.append(cmd)
        if cmd == ["claude", "auth", "login"]:
            return _FakeCompleted("")
        # Logged out on the first status check, logged in on the recheck
        # after login runs.
        logged_in = calls.count(["claude", "auth", "status", "--json"]) > 1
        return _FakeCompleted(json.dumps({"loggedIn": logged_in}))

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert claude_login.ensure_logged_in() is True
    assert calls == [
        ["claude", "auth", "status", "--json"],
        ["claude", "auth", "login"],
        ["claude", "auth", "status", "--json"],
    ]


def test_ensure_logged_in_returns_false_if_login_still_fails(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: _FakeCompleted(json.dumps({"loggedIn": False}))
    )
    assert claude_login.ensure_logged_in() is False
