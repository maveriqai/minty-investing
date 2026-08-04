"""Tests engine/reminder/cli.py's argument parsing against a fake backend
(via a monkeypatched select_backend) — proves the CLI wires args to the
right backend calls, independent of which real OS backend would be
selected.
"""

import sys

from engine.reminder import base, cli
from engine.reminder.base import ReminderStatus


class _FakeBackend:
    def __init__(self):
        self.install_calls = []
        self.uninstall_calls = 0
        self.status_result = ReminderStatus(installed=True, detail="fake")

    def install(self, time, message):
        self.install_calls.append((time, message))

    def uninstall(self):
        self.uninstall_calls += 1

    def status(self):
        return self.status_result


def _run_cli(argv, monkeypatch, capsys):
    fake = _FakeBackend()
    monkeypatch.setattr(base, "select_backend", lambda: fake)
    monkeypatch.setattr(cli, "select_backend", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["cli"] + argv)
    cli.main()
    return fake, capsys.readouterr().out


def test_install_uses_default_time_and_message_when_omitted(monkeypatch, capsys):
    fake, out = _run_cli(["install"], monkeypatch, capsys)
    assert fake.install_calls == [(base.DEFAULT_TIME, base.DEFAULT_MESSAGE)]
    assert "Reminder installed" in out


def test_install_passes_through_custom_time_and_message(monkeypatch, capsys):
    fake, _out = _run_cli(["install", "--time", "09:00", "--message", "custom nudge"], monkeypatch, capsys)
    assert fake.install_calls == [("09:00", "custom nudge")]


def test_uninstall_calls_backend_uninstall(monkeypatch, capsys):
    fake, out = _run_cli(["uninstall"], monkeypatch, capsys)
    assert fake.uninstall_calls == 1
    assert "Reminder uninstalled" in out


def test_status_prints_backend_status(monkeypatch, capsys):
    _fake, out = _run_cli(["status"], monkeypatch, capsys)
    assert "installed=True" in out
    assert "fake" in out
