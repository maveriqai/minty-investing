"""Tests for engine/workspace.py — deterministic workspace resolution and
change-tracking, built so "which directory" stops being a model decision
and "did anything actually get saved" stops being taken on the model's
word alone.
"""

import time

from engine.workspace import (
    changed_since,
    is_within_known_workspace_roots,
    resolve_active_workspace,
    resolve_workspace,
    snapshot,
)


def test_resolve_workspace_creates_data_and_results_subdirs(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")
    root = resolve_workspace("test-scan")

    assert root == tmp_path / ".dev-workspaces" / "test-scan"
    assert (root / "data").is_dir()
    assert (root / "results").is_dir()


def test_resolve_workspace_is_idempotent(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")
    first = resolve_workspace("test-scan")
    (first / "results" / "existing.md").write_text("hello")

    second = resolve_workspace("test-scan")

    assert second == first
    assert (second / "results" / "existing.md").read_text() == "hello"


def test_resolve_active_workspace_defaults_to_the_fixed_workspace_root(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.delenv("MINTY_WORKSPACE", raising=False)

    root = resolve_active_workspace()

    assert root == tmp_path / "workspace"
    assert (root / "data").is_dir()
    assert (root / "results").is_dir()


def test_resolve_active_workspace_honors_minty_workspace_env_override(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")
    monkeypatch.setenv("MINTY_WORKSPACE", "test-scratch")

    root = resolve_active_workspace()

    assert root == tmp_path / ".dev-workspaces" / "test-scratch"
    assert not (tmp_path / "workspace").exists()


def test_is_within_known_workspace_roots_accepts_the_fixed_workspace(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")
    (tmp_path / "workspace").mkdir()

    assert is_within_known_workspace_roots(tmp_path / "workspace")
    assert is_within_known_workspace_roots(tmp_path / "workspace" / "data")


def test_is_within_known_workspace_roots_accepts_a_dev_sandbox(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")

    assert is_within_known_workspace_roots(tmp_path / ".dev-workspaces" / "test-scratch")


def test_is_within_known_workspace_roots_rejects_an_unrelated_path(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(ws, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")

    assert not is_within_known_workspace_roots(tmp_path / "not-a-workspace")


def test_snapshot_reflects_only_files_currently_present(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "a.json").write_text("{}")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "b.json").write_text("{}")

    snap = snapshot(tmp_path)

    assert set(snap.keys()) == {
        str(tmp_path / "results" / "a.json"),
        str(tmp_path / "data" / "b.json"),
    }


def test_changed_since_detects_new_file(tmp_path):
    (tmp_path / "results").mkdir()
    before = snapshot(tmp_path)

    (tmp_path / "results" / "new.md").write_text("content")

    assert changed_since(tmp_path, before) == [str(tmp_path / "results" / "new.md")]


def test_changed_since_detects_modified_file(tmp_path):
    (tmp_path / "results").mkdir()
    f = tmp_path / "results" / "existing.md"
    f.write_text("v1")
    before = snapshot(tmp_path)

    time.sleep(0.01)
    f.write_text("v2 — longer content so mtime resolution differences don't matter")

    assert changed_since(tmp_path, before) == [str(f)]


def test_changed_since_returns_empty_when_nothing_changed(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "existing.md").write_text("v1")
    before = snapshot(tmp_path)

    assert changed_since(tmp_path, before) == []
