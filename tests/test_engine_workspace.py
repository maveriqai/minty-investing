"""Tests for engine/workspace.py — deterministic workspace resolution and
change-tracking, built so "which directory" stops being a model decision
and "did anything actually get saved" stops being taken on the model's
word alone.
"""

import time

from engine.workspace import changed_since, resolve_workspace, snapshot


def test_resolve_workspace_creates_data_and_results_subdirs(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACES_ROOT", tmp_path / "workspaces")
    root = resolve_workspace("test-scan")

    assert root == tmp_path / "workspaces" / "test-scan"
    assert (root / "data").is_dir()
    assert (root / "results").is_dir()


def test_resolve_workspace_is_idempotent(tmp_path, monkeypatch):
    import engine.workspace as ws

    monkeypatch.setattr(ws, "WORKSPACES_ROOT", tmp_path / "workspaces")
    first = resolve_workspace("test-scan")
    (first / "results" / "existing.md").write_text("hello")

    second = resolve_workspace("test-scan")

    assert second == first
    assert (second / "results" / "existing.md").read_text() == "hello"


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
