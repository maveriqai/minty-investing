"""Unit tests for engine/feedback_issue.py's file_feedback_issue tool —
issue #73's redesigned /feedback, the "share with the Minty team?" half."""

import asyncio

import engine.feedback_issue as feedback_issue_module
from engine.feedback import feedback_path
from engine.feedback_issue import (
    _fallback_command,
    _run_gh_issue_create,
    build_feedback_issue_server,
    build_feedback_issue_tool,
)


def _run(coro):
    return asyncio.run(coro)


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")


class _FakeProc:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False
        self.waited = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


class _NeverEndingProc:
    def __init__(self):
        self.killed = False
        self.waited = False

    async def communicate(self):
        await asyncio.sleep(1000)

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


def test_handler_rejects_workspace_root_outside_known_workspace_roots(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()
    tool = build_feedback_issue_tool()

    result = _run(
        tool.handler({"workspace_root": str(outside), "title": "t", "body": "b", "share": True})
    )

    assert result["is_error"] is True


def test_handler_share_false_saves_locally_and_never_touches_the_subprocess(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("share=False must never touch the subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_if_called)
    tool = build_feedback_issue_tool()

    result = _run(
        tool.handler({"workspace_root": str(workspace), "title": "Title", "body": "Body", "share": False})
    )

    assert "not shared" in result["content"][0]["text"].lower()
    text = feedback_path(workspace).read_text()
    assert "Not shared with the Minty team (kept local only)." in text


def test_run_gh_issue_create_uses_a_fixed_argv_not_a_shell(monkeypatch):
    captured = {}

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProc(0, stdout=b"https://github.com/maveriqai/minty-investing/issues/101\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    ok, issue_url, error = _run(_run_gh_issue_create("A title", "A body"))

    assert ok is True
    assert issue_url == "https://github.com/maveriqai/minty-investing/issues/101"
    assert error == ""
    assert captured["args"] == (
        "gh",
        "issue",
        "create",
        "--repo",
        "maveriqai/minty-investing",
        "--title",
        "A title",
        "--body",
        "A body",
    )
    assert "shell" not in captured["kwargs"]


def test_run_gh_issue_create_sets_stdin_to_devnull(monkeypatch):
    captured = {}

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeProc(0, stdout=b"https://github.com/x/y/issues/1")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    _run(_run_gh_issue_create("t", "b"))

    assert captured["kwargs"]["stdin"] == asyncio.subprocess.DEVNULL


def test_run_gh_issue_create_times_out_and_kills_the_process(monkeypatch):
    proc = _NeverEndingProc()

    async def _fake_create_subprocess_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(feedback_issue_module, "_GH_TIMEOUT_S", 0.05)

    ok, issue_url, error = _run(_run_gh_issue_create("t", "b"))

    assert ok is False
    assert issue_url == ""
    assert "timed out" in error
    assert proc.killed is True


def test_run_gh_issue_create_returns_failure_on_non_zero_exit(monkeypatch):
    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProc(1, stderr=b"gh: not authenticated")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    ok, issue_url, error = _run(_run_gh_issue_create("t", "b"))

    assert ok is False
    assert issue_url == ""
    assert "not authenticated" in error


def test_run_gh_issue_create_returns_failure_when_gh_is_not_installed(monkeypatch):
    async def _raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("no such file: gh")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_file_not_found)

    ok, issue_url, error = _run(_run_gh_issue_create("t", "b"))

    assert ok is False
    assert issue_url == ""
    assert error


def test_handler_share_true_success_appends_the_issue_url_and_returns_it(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def _fake_run_gh_issue_create(title, body):
        return True, "https://github.com/maveriqai/minty-investing/issues/102", ""

    monkeypatch.setattr(feedback_issue_module, "_run_gh_issue_create", _fake_run_gh_issue_create)
    tool = build_feedback_issue_tool()

    result = _run(
        tool.handler({"workspace_root": str(workspace), "title": "Title", "body": "Body", "share": True})
    )

    assert "https://github.com/maveriqai/minty-investing/issues/102" in result["content"][0]["text"]
    text = feedback_path(workspace).read_text()
    assert "Shared as: https://github.com/maveriqai/minty-investing/issues/102" in text


def test_handler_share_true_failure_falls_back_to_a_pre_filled_command_and_still_saves_locally(
    tmp_path, monkeypatch
):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def _fake_run_gh_issue_create(title, body):
        return False, "", "gh: not authenticated"

    monkeypatch.setattr(feedback_issue_module, "_run_gh_issue_create", _fake_run_gh_issue_create)
    tool = build_feedback_issue_tool()

    result = _run(
        tool.handler({"workspace_root": str(workspace), "title": "Title", "body": "Body", "share": True})
    )

    returned_text = result["content"][0]["text"]
    assert "gh issue create --repo maveriqai/minty-investing" in returned_text
    saved_text = feedback_path(workspace).read_text()
    assert "Not shared automatically — run this yourself:" in saved_text
    assert "gh issue create --repo maveriqai/minty-investing" in saved_text


def test_fallback_command_shell_quotes_title_and_body_safely():
    import shlex

    command = _fallback_command('Title with "quotes"', "Body with a $(dangerous) substitution and spaces")

    parts = shlex.split(command)
    assert parts[:4] == ["gh", "issue", "create", "--repo"]
    assert 'Title with "quotes"' in parts
    assert "Body with a $(dangerous) substitution and spaces" in parts


def test_build_feedback_issue_server_registers_file_feedback_issue_tool():
    server = build_feedback_issue_server()
    assert server is not None
