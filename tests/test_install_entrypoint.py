"""Tests for scripts/install_entrypoint.py — the confirmation gate for
issue #34 (installing minty from a second clone silently repoints the
global `minty` command, since every clone resolves to the identical
package identity `minty-investing==0.1.0`).
"""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "install_entrypoint.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ie = _load("install_entrypoint", _SCRIPT_PATH)


def _fake_run_uv_tool_dir(tools_dir: Path):
    """Returns a fake subprocess.run that answers `uv tool dir` with
    `tools_dir` and errors on anything else (the real install call is
    monkeypatched separately in tests that reach it)."""

    def _fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "tool"] and cmd[2] == "dir":
            return SimpleNamespace(stdout=str(tools_dir) + "\n")
        raise AssertionError(f"unexpected subprocess.run call: {cmd}")

    return _fake_run


def _write_direct_url(tools_dir: Path, points_at: Path):
    dist_info = (
        tools_dir / ie.PACKAGE_NAME / "lib" / "python3.12" / "site-packages" / f"{ie.DIST_NAME}-0.1.0.dist-info"
    )
    dist_info.mkdir(parents=True)
    (dist_info / "direct_url.json").write_text(
        json.dumps({"url": f"file://{points_at}", "dir_info": {"editable": True}})
    )


def test_find_existing_install_path_returns_none_when_uv_tool_dir_has_no_install(tmp_path, monkeypatch):
    tools_dir = tmp_path / "uv-tools"
    tools_dir.mkdir()
    monkeypatch.setattr(subprocess, "run", _fake_run_uv_tool_dir(tools_dir))

    assert ie._find_existing_install_path() is None


def test_find_existing_install_path_parses_direct_url_json(tmp_path, monkeypatch):
    tools_dir = tmp_path / "uv-tools"
    other_repo = tmp_path / "other-clone"
    other_repo.mkdir()
    _write_direct_url(tools_dir, other_repo)
    monkeypatch.setattr(subprocess, "run", _fake_run_uv_tool_dir(tools_dir))

    assert ie._find_existing_install_path() == other_repo.resolve()


def test_find_existing_install_path_returns_none_when_uv_tool_dir_fails(monkeypatch):
    def _fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert ie._find_existing_install_path() is None


def test_main_no_prior_install_proceeds_without_prompt(monkeypatch):
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: None)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)

    def _no_input(*a, **k):
        raise AssertionError("should not prompt")

    monkeypatch.setattr("builtins.input", _no_input)

    assert ie.main([]) == 0
    assert calls == ["installed"]


def test_main_prior_install_same_path_proceeds_without_prompt(monkeypatch):
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: ie.REPO_ROOT)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)
    monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not prompt")))

    assert ie.main([]) == 0
    assert calls == ["installed"]


def test_main_prior_install_different_path_confirmed_proceeds(tmp_path, monkeypatch):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    assert ie.main([]) == 0
    assert calls == ["installed"]


def test_main_prior_install_different_path_declined_aborts(tmp_path, monkeypatch):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    assert ie.main([]) == 1
    assert calls == []


def test_main_prior_install_different_path_blank_answer_aborts(tmp_path, monkeypatch):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")

    assert ie.main([]) == 1
    assert calls == []


def test_main_yes_flag_skips_prompt_even_with_a_conflict(tmp_path, monkeypatch):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)
    monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not prompt")))

    assert ie.main(["--yes"]) == 0
    assert calls == ["installed"]


def test_main_where_flag_prints_existing_install_path(tmp_path, monkeypatch, capsys):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)

    assert ie.main(["--where"]) == 0
    assert capsys.readouterr().out.strip() == str(other)


def test_main_where_flag_no_prior_install_reports_none(monkeypatch, capsys):
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: None)

    assert ie.main(["--where"]) == 1
    assert "No `minty` install found" in capsys.readouterr().out


def test_main_eof_from_input_is_treated_as_decline(tmp_path, monkeypatch):
    other = tmp_path / "other-clone"
    monkeypatch.setattr(ie, "_find_existing_install_path", lambda: other)
    calls = []
    monkeypatch.setattr(ie, "_run_install", lambda: calls.append("installed") or 0)

    def _raise_eof(*a, **k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)

    assert ie.main([]) == 1
    assert calls == []
