"""Unit tests for engine/workspace_notes.py's update_workspace_notes tool —
the fix for the model improvising its own filename instead of the
documented workspace notes.md, found live during the 2026-08-04
compounding-proof test.
"""

import asyncio

from engine.workspace_notes import (
    _resolve_target,
    _resolve_workspace_root,
    build_workspace_notes_tool,
)


def _run(coro):
    return asyncio.run(coro)


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")


def test_resolve_workspace_root_accepts_the_fixed_workspace(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert _resolve_workspace_root(str(workspace)) == workspace.resolve()


def test_resolve_workspace_root_accepts_a_dev_sandbox(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / ".dev-workspaces" / "my-workspace"
    workspace.mkdir(parents=True)

    assert _resolve_workspace_root(str(workspace)) == workspace.resolve()


def test_resolve_workspace_root_rejects_path_outside_known_roots(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()

    assert _resolve_workspace_root(str(outside)) is None


def test_resolve_workspace_root_rejects_nonexistent_path(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)

    assert _resolve_workspace_root(str(tmp_path / "workspace" / "does-not-exist")) is None


def test_resolve_target_defaults_and_thesis_files():
    assert _resolve_target("notes.md") == "notes.md"
    assert _resolve_target("theses/RELIANCE.md") == "theses/RELIANCE.md"
    assert _resolve_target("theses/M&M.md") == "theses/M&M.md"


def test_resolve_target_rejects_anything_else():
    assert _resolve_target("../escape.md") is None
    assert _resolve_target("data/holdings.json") is None
    assert _resolve_target("theses/reliance.md") is None  # must be uppercase


def test_update_workspace_notes_tool_writes_to_notes_md_by_default(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    update_tool = build_workspace_notes_tool()
    assert update_tool.name == "update_workspace_notes"

    result = _run(update_tool.handler({"workspace_root": str(workspace), "content": "# Notes\n\nfinding one"}))

    assert result.get("is_error") is not True
    notes_path = workspace / "notes.md"
    assert notes_path.read_text() == "# Notes\n\nfinding one"


def test_update_workspace_notes_tool_overwrites_with_merged_content(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.md").write_text("# Notes\n\noriginal")

    update_tool = build_workspace_notes_tool()
    _run(update_tool.handler({"workspace_root": str(workspace), "content": "# Notes\n\noriginal\nmerged addition"}))

    assert (workspace / "notes.md").read_text() == "# Notes\n\noriginal\nmerged addition"


def test_update_workspace_notes_tool_writes_to_a_thesis_file(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    update_tool = build_workspace_notes_tool()
    result = _run(
        update_tool.handler(
            {"workspace_root": str(workspace), "target": "theses/RELIANCE.md", "content": "# RELIANCE thesis"}
        )
    )

    assert result.get("is_error") is not True
    assert (workspace / "theses" / "RELIANCE.md").read_text() == "# RELIANCE thesis"
    assert not (workspace / "notes.md").exists()


def test_update_workspace_notes_tool_rejects_an_invalid_target(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    update_tool = build_workspace_notes_tool()
    result = _run(
        update_tool.handler({"workspace_root": str(workspace), "target": "../escape.md", "content": "malicious"})
    )

    assert result.get("is_error") is True


def test_update_workspace_notes_tool_rejects_path_outside_known_roots(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()

    update_tool = build_workspace_notes_tool()
    result = _run(update_tool.handler({"workspace_root": str(outside), "content": "malicious"}))

    assert result.get("is_error") is True
    assert not (outside / "notes.md").exists()
