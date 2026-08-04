"""Windows Task Scheduler-backed reminder backend — installs a scheduled
task that runs a small PowerShell script displaying a native Windows toast
notification Mon-Fri at a configured local time, via the WinRT toast APIs
built into Windows 10+ (`Windows.UI.Notifications`). Deliberately avoids
any third-party PowerShell module (e.g. BurntToast) so nothing needs a
prior `Install-Module` step on the user's machine — just `schtasks.exe`
and `powershell.exe`, both always present on Windows.

**Not live-verified.** This project is developed on macOS (no Windows
machine available) — built from documented `schtasks` flags and the
widely-published WinRT-toast-from-PowerShell technique, and covered by
unit tests on the command/script construction (mocked subprocess calls),
not a real scheduled task actually firing. Flag this clearly if a real
Windows run ever surfaces a problem — the macOS backend's docstring shows
what a genuine live-verification note looks like once this one exists.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from engine.reminder.base import DEFAULT_MESSAGE, DEFAULT_TIME, ReminderStatus, parse_time

TASK_NAME = "MintyMorningDigestReminder"
SCRIPT_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / "Minty" / "reminder_notify.ps1"

_SCHTASKS_WEEKDAYS = "MON,TUE,WED,THU,FRI"


def _build_powershell_script(message: str) -> str:
    # PowerShell single-quoted string literal — only a literal ' needs
    # escaping (doubled), unlike a double-quoted string's backtick/$ rules.
    escaped = message.replace("'", "''")
    return f"""$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).AppendChild($template.CreateTextNode('Minty')) | Out-Null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{escaped}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Minty').Show($toast)
"""


def _build_schtasks_create_command(time: str) -> list[str]:
    hour, minute = parse_time(time)
    return [
        "schtasks",
        "/Create",
        "/F",  # overwrite a pre-existing task of the same name — idempotent reinstall
        "/TN",
        TASK_NAME,
        "/SC",
        "WEEKLY",
        "/D",
        _SCHTASKS_WEEKDAYS,
        "/ST",
        f"{hour:02d}:{minute:02d}",
        "/TR",
        f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{SCRIPT_PATH}"',
    ]


def _build_schtasks_delete_command() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def _build_schtasks_query_command() -> list[str]:
    return ["schtasks", "/Query", "/TN", TASK_NAME]


class WindowsReminderBackend:
    def install(self, time: str = DEFAULT_TIME, message: str = DEFAULT_MESSAGE) -> None:
        SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCRIPT_PATH.write_text(_build_powershell_script(message))
        subprocess.run(_build_schtasks_create_command(time), check=True, capture_output=True)

    def uninstall(self) -> None:
        subprocess.run(_build_schtasks_delete_command(), capture_output=True, check=False)
        if SCRIPT_PATH.exists():
            SCRIPT_PATH.unlink()

    def status(self) -> ReminderStatus:
        result = subprocess.run(_build_schtasks_query_command(), capture_output=True, text=True, check=False)
        installed = result.returncode == 0
        detail = f"task {TASK_NAME!r} " + ("found in Task Scheduler" if installed else "not found in Task Scheduler")
        return ReminderStatus(installed=installed, detail=detail)


__all__ = ["SCRIPT_PATH", "TASK_NAME", "WindowsReminderBackend"]
