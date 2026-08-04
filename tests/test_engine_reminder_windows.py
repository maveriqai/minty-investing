"""Unit tests for engine/reminder/windows.py — schtasks/PowerShell command
construction plus install/uninstall/status against a fake `subprocess.run`,
no real Task Scheduler touched. Covers construction logic only — see the
module's own docstring for why this backend isn't live-verified.
"""

from engine.reminder import windows


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


def test_build_powershell_script_embeds_message_and_uses_winrt_toast_apis():
    script = windows._build_powershell_script("go run the digest")
    assert "go run the digest" in script
    assert "Windows.UI.Notifications.ToastNotificationManager" in script
    assert "ToastNotification" in script


def test_build_powershell_script_escapes_single_quotes():
    script = windows._build_powershell_script("it's time")
    assert "it''s time" in script


def test_build_schtasks_create_command_has_weekly_mon_fri_trigger_and_time():
    command = windows._build_schtasks_create_command("08:30")
    assert command[:2] == ["schtasks", "/Create"]
    assert "/SC" in command and command[command.index("/SC") + 1] == "WEEKLY"
    assert "/D" in command and command[command.index("/D") + 1] == "MON,TUE,WED,THU,FRI"
    assert "/ST" in command and command[command.index("/ST") + 1] == "08:30"
    assert windows.TASK_NAME in command


def test_build_schtasks_create_command_runs_the_notify_script_via_powershell():
    command = windows._build_schtasks_create_command("08:30")
    tr_value = command[command.index("/TR") + 1]
    assert "powershell.exe" in tr_value
    assert str(windows.SCRIPT_PATH) in tr_value


def test_build_schtasks_delete_and_query_commands_target_the_same_task_name():
    delete_command = windows._build_schtasks_delete_command()
    query_command = windows._build_schtasks_query_command()
    assert windows.TASK_NAME in delete_command
    assert windows.TASK_NAME in query_command


def test_install_writes_notify_script_and_creates_scheduled_task(monkeypatch, tmp_path):
    script_path = tmp_path / "Minty" / "reminder_notify.ps1"
    monkeypatch.setattr(windows, "SCRIPT_PATH", script_path)
    fake = _FakeSubprocess()
    monkeypatch.setattr(windows, "subprocess", fake)

    windows.WindowsReminderBackend().install("08:30", "go run the digest")

    assert script_path.exists()
    assert "go run the digest" in script_path.read_text()
    assert fake.calls[-1][:2] == ["schtasks", "/Create"]


def test_uninstall_deletes_task_and_removes_script(monkeypatch, tmp_path):
    script_path = tmp_path / "Minty" / "reminder_notify.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("existing")
    monkeypatch.setattr(windows, "SCRIPT_PATH", script_path)
    fake = _FakeSubprocess()
    monkeypatch.setattr(windows, "subprocess", fake)

    windows.WindowsReminderBackend().uninstall()

    assert not script_path.exists()
    assert fake.calls[-1] == ["schtasks", "/Delete", "/TN", windows.TASK_NAME, "/F"]


def test_status_reports_installed_when_task_found(monkeypatch, tmp_path):
    monkeypatch.setattr(windows, "subprocess", _FakeSubprocess(returncode=0))
    status = windows.WindowsReminderBackend().status()
    assert status.installed is True


def test_status_reports_not_installed_when_task_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(windows, "subprocess", _FakeSubprocess(returncode=1))
    status = windows.WindowsReminderBackend().status()
    assert status.installed is False
