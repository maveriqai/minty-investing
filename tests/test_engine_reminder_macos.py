"""Unit tests for engine/reminder/macos.py — plist/helper-script
construction plus install/uninstall/status against a fake `subprocess.run`
and a monkeypatched PLIST_PATH, no real launchd touched. Covers both the
terminal-notifier and plain-osascript program-argument paths.
"""

from pathlib import Path

from engine.reminder import macos


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class _FakeSubprocess:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def run(self, args, **kwargs):
        self.calls.append(list(args))
        return _FakeCompletedProcess(self.returncode)


def test_osascript_program_arguments_embeds_message():
    args = macos._osascript_program_arguments("hello there")
    assert args[0] == "/usr/bin/osascript"
    assert "hello there" in args[-1]


def test_osascript_program_arguments_escapes_quotes_and_backslashes():
    args = macos._osascript_program_arguments('say "hi" \\ bye')
    assert '\\"hi\\"' in args[-1]
    assert "\\\\ bye" in args[-1]


def test_terminal_notifier_program_arguments_wires_execute_to_open_terminal_script():
    args = macos._terminal_notifier_program_arguments("/opt/homebrew/bin/terminal-notifier", "go run it")
    assert args[0] == "/opt/homebrew/bin/terminal-notifier"
    assert "-message" in args and args[args.index("-message") + 1] == "go run it"
    execute_value = args[args.index("-execute") + 1]
    assert str(macos.OPEN_TERMINAL_SCRIPT) in execute_value


def test_build_open_terminal_script_cds_into_repo_root_via_terminal_app():
    script = macos._build_open_terminal_script(Path("/Users/someone/minty-investing"))
    assert script.startswith("#!/bin/bash")
    assert "Terminal" in script
    assert "/Users/someone/minty-investing" in script


def test_build_plist_contains_five_weekday_intervals_with_given_time():
    plist = macos._build_plist(8, 30, ["/usr/bin/osascript", "-e", "display notification"])
    assert plist.count("<key>Weekday</key>") == 5
    for weekday in range(1, 6):
        assert f"<integer>{weekday}</integer>" in plist
    assert "<key>Hour</key><integer>8</integer>" in plist
    assert "<key>Minute</key><integer>30</integer>" in plist


def test_build_plist_embeds_each_program_argument_as_its_own_xml_string():
    plist = macos._build_plist(9, 0, ["/usr/bin/osascript", "-e", "display notification"])
    assert "<string>/usr/bin/osascript</string>" in plist
    assert "<string>-e</string>" in plist
    assert "<string>display notification</string>" in plist


def test_build_plist_xml_escapes_special_characters_in_arguments():
    plist = macos._build_plist(9, 0, ["cmd", "a & b < c"])
    assert "a &amp; b &lt; c" in plist


def test_install_prefers_terminal_notifier_when_available(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    script_path = tmp_path / "AppSupport" / "reminder_open_terminal.sh"
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "OPEN_TERMINAL_SCRIPT", script_path)
    monkeypatch.setattr(macos, "_which_terminal_notifier", lambda: "/opt/homebrew/bin/terminal-notifier")
    fake = _FakeSubprocess()
    monkeypatch.setattr(macos, "subprocess", fake)

    macos.MacOSReminderBackend().install("08:30", "go run the digest")

    assert script_path.exists()
    assert script_path.stat().st_mode & 0o777 == 0o700
    plist_content = plist_path.read_text()
    assert "terminal-notifier" in plist_content
    assert "go run the digest" in plist_content
    assert "osascript" not in plist_content.split("<key>ProgramArguments</key>")[1].split("</array>")[0]


def test_install_falls_back_to_osascript_when_terminal_notifier_missing(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    script_path = tmp_path / "AppSupport" / "reminder_open_terminal.sh"
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "OPEN_TERMINAL_SCRIPT", script_path)
    monkeypatch.setattr(macos, "_which_terminal_notifier", lambda: None)
    fake = _FakeSubprocess()
    monkeypatch.setattr(macos, "subprocess", fake)

    macos.MacOSReminderBackend().install("08:30", "go run the digest")

    assert not script_path.exists()
    plist_content = plist_path.read_text()
    assert "/usr/bin/osascript" in plist_content
    assert "go run the digest" in plist_content


def test_install_loads_the_plist_via_launchctl(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "OPEN_TERMINAL_SCRIPT", tmp_path / "reminder_open_terminal.sh")
    monkeypatch.setattr(macos, "_which_terminal_notifier", lambda: None)
    fake = _FakeSubprocess()
    monkeypatch.setattr(macos, "subprocess", fake)

    macos.MacOSReminderBackend().install("08:30", "go run the digest")

    assert fake.calls[-2] == ["launchctl", "unload", str(plist_path)]
    assert fake.calls[-1] == ["launchctl", "load", str(plist_path)]


def test_uninstall_unloads_removes_plist_and_helper_script(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("existing content")
    script_path = tmp_path / "AppSupport" / "reminder_open_terminal.sh"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("existing script")
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "OPEN_TERMINAL_SCRIPT", script_path)
    fake = _FakeSubprocess()
    monkeypatch.setattr(macos, "subprocess", fake)

    macos.MacOSReminderBackend().uninstall()

    assert not plist_path.exists()
    assert not script_path.exists()
    assert ["launchctl", "unload", str(plist_path)] in fake.calls


def test_uninstall_is_a_noop_when_nothing_installed(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "OPEN_TERMINAL_SCRIPT", tmp_path / "reminder_open_terminal.sh")
    fake = _FakeSubprocess()
    monkeypatch.setattr(macos, "subprocess", fake)

    macos.MacOSReminderBackend().uninstall()  # must not raise

    assert fake.calls == []


def test_status_reports_not_installed_when_no_plist(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)

    status = macos.MacOSReminderBackend().status()

    assert status.installed is False


def test_status_reports_installed_when_plist_exists_and_launchd_confirms(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("content")
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "subprocess", _FakeSubprocess(returncode=0))

    status = macos.MacOSReminderBackend().status()

    assert status.installed is True


def test_status_reports_plist_present_but_not_loaded(monkeypatch, tmp_path):
    plist_path = tmp_path / "LaunchAgents" / f"{macos.LABEL}.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("content")
    monkeypatch.setattr(macos, "PLIST_PATH", plist_path)
    monkeypatch.setattr(macos, "subprocess", _FakeSubprocess(returncode=1))

    status = macos.MacOSReminderBackend().status()

    assert status.installed is False
    assert "NOT currently loaded" in status.detail
