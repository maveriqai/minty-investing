"""Unit tests for engine/workspace_notes.py's update_workspace_notes tool —
the fix for the model improvising its own filename instead of the
documented workspace notes.md, found live during the 2026-08-04
compounding-proof test.
"""

import asyncio

from engine.workspace_notes import _resolve_workspace_root, build_workspace_notes_tool


def _run(coro):
    return asyncio.run(coro)


def test_resolve_workspace_root_accepts_real_dir_under_workspaces_root(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspace = workspaces_root / "my-workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    assert _resolve_workspace_root(str(workspace)) == workspace.resolve()


def test_resolve_workspace_root_rejects_path_outside_workspaces_root(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspaces_root.mkdir()
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    assert _resolve_workspace_root(str(outside)) is None


def test_resolve_workspace_root_rejects_nonexistent_path(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspaces_root.mkdir()
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    assert _resolve_workspace_root(str(workspaces_root / "does-not-exist")) is None


def test_update_workspace_notes_tool_writes_to_notes_md(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspace = workspaces_root / "my-workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    update_tool = build_workspace_notes_tool()
    assert update_tool.name == "update_workspace_notes"

    result = _run(update_tool.handler({"workspace_root": str(workspace), "content": "# Notes\n\nfinding one"}))

    assert result.get("is_error") is not True
    notes_path = workspace / "notes.md"
    assert notes_path.read_text() == "# Notes\n\nfinding one"


def test_update_workspace_notes_tool_overwrites_with_merged_content(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspace = workspaces_root / "my-workspace"
    workspace.mkdir(parents=True)
    (workspace / "notes.md").write_text("# Notes\n\noriginal")
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    update_tool = build_workspace_notes_tool()
    _run(update_tool.handler({"workspace_root": str(workspace), "content": "# Notes\n\noriginal\nmerged addition"}))

    assert (workspace / "notes.md").read_text() == "# Notes\n\noriginal\nmerged addition"


def test_update_workspace_notes_tool_rejects_path_outside_workspaces_root(tmp_path, monkeypatch):
    import engine.workspace_notes as workspace_notes_module

    workspaces_root = tmp_path / "workspaces"
    workspaces_root.mkdir()
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()
    monkeypatch.setattr(workspace_notes_module, "WORKSPACES_ROOT", workspaces_root)

    update_tool = build_workspace_notes_tool()
    result = _run(update_tool.handler({"workspace_root": str(outside), "content": "malicious"}))

    assert result.get("is_error") is True
    assert not (outside / "notes.md").exists()
