"""Tests for engine/kite_status.py's deterministic Zerodha-connection
status line — the Kite counterpart to engine/claude_login.py's Claude
check. No MCP call, no model turn; just two local files (see
docs/next-phase-plan.md §5.1).
"""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from engine.kite_status import kite_connection_status_line

_IST = ZoneInfo("Asia/Kolkata")


def _write_identity(repo_root, user_id="AB1234"):
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "account_identity.json").write_text(
        json.dumps({"source": "kite", "as_of": "2026-08-19 09:00 IST", "data": {"user_id": user_id}})
    )


def _write_holdings(workspace_root, as_of: date):
    data_dir = workspace_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"holdings_{as_of.isoformat()}.json").write_text("[]")


def _patch_repo_root(monkeypatch, repo_root):
    import engine.kite_status as kite_status_module

    monkeypatch.setattr(kite_status_module, "ACCOUNT_IDENTITY_FILE", repo_root / "data" / "account_identity.json")


def test_not_connected_when_neither_file_exists(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    line = kite_connection_status_line(workspace_root)

    assert line.startswith("Zerodha not connected yet")


def test_not_connected_when_identity_exists_but_no_holdings(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    _write_identity(tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    line = kite_connection_status_line(workspace_root)

    assert line.startswith("Zerodha not connected yet")


def test_not_connected_when_holdings_exist_but_no_identity(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    workspace_root = tmp_path / "workspace"
    _write_holdings(workspace_root, datetime.now(_IST).date())

    line = kite_connection_status_line(workspace_root)

    assert line.startswith("Zerodha not connected yet")


def test_connected_reports_account_and_days_since_refresh(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    _write_identity(tmp_path, user_id="AB1234")
    workspace_root = tmp_path / "workspace"
    two_days_ago = datetime.now(_IST).date() - timedelta(days=2)
    _write_holdings(workspace_root, two_days_ago)

    line = kite_connection_status_line(workspace_root)

    assert line == "Holdings for account AB1234 found — last refreshed 2 days ago."


def test_connected_today_reads_as_today_not_zero_days(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    _write_identity(tmp_path, user_id="AB1234")
    workspace_root = tmp_path / "workspace"
    _write_holdings(workspace_root, datetime.now(_IST).date())

    line = kite_connection_status_line(workspace_root)

    assert line == "Holdings for account AB1234 found — last refreshed today."


def test_connected_one_day_ago_is_singular(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    _write_identity(tmp_path, user_id="AB1234")
    workspace_root = tmp_path / "workspace"
    _write_holdings(workspace_root, datetime.now(_IST).date() - timedelta(days=1))

    line = kite_connection_status_line(workspace_root)

    assert line == "Holdings for account AB1234 found — last refreshed 1 day ago."


def test_picks_the_newest_holdings_file_by_filename_date_not_mtime(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    _write_identity(tmp_path, user_id="AB1234")
    workspace_root = tmp_path / "workspace"
    today = datetime.now(_IST).date()
    # Write the older file *after* the newer one, so mtime would pick the
    # wrong one if this function used mtime instead of the filename date.
    _write_holdings(workspace_root, today)
    _write_holdings(workspace_root, today - timedelta(days=5))

    line = kite_connection_status_line(workspace_root)

    assert line == "Holdings for account AB1234 found — last refreshed today."


def test_falls_through_to_not_connected_on_corrupt_identity_file(tmp_path, monkeypatch):
    _patch_repo_root(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "account_identity.json").write_text("not valid json")
    workspace_root = tmp_path / "workspace"
    _write_holdings(workspace_root, datetime.now(_IST).date())

    line = kite_connection_status_line(workspace_root)

    assert line.startswith("Zerodha not connected yet")
