"""Tests for engine/memory_candidates.py — issue #14 piece 2/3's staging
queue between a turn noticing something durable and a human actually
confirming it into notes.md.
"""

import asyncio
from datetime import datetime

from engine.memory_candidates import (
    append_candidate,
    build_memory_candidate_tool,
    candidates_path,
    read_and_clear,
)
from engine.time_ist import IST as _IST


def _run(coro):
    return asyncio.run(coro)


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")


def test_candidates_path_is_a_top_level_workspace_file(tmp_path):
    assert candidates_path(tmp_path) == tmp_path / "memory_candidates.md"


def test_read_and_clear_returns_empty_string_when_never_created(tmp_path):
    assert read_and_clear(tmp_path / "memory_candidates.md") == ""


def test_append_candidate_creates_the_file_with_content_and_grounding(tmp_path):
    path = tmp_path / "memory_candidates.md"
    now = datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST)

    append_candidate(path, "User seems done with PSU banks.", "from this turn's discussion", now=now)

    text = path.read_text()
    assert "## candidate (2026-08-25 09:00 IST)" in text
    assert "User seems done with PSU banks." in text
    assert "Grounding: from this turn's discussion" in text


def test_append_candidate_appends_multiple_without_overwriting(tmp_path):
    path = tmp_path / "memory_candidates.md"
    first = datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST)
    second = datetime(2026, 8, 25, 9, 5, 0, tzinfo=_IST)

    append_candidate(path, "first fact", "grounding one", now=first)
    append_candidate(path, "second fact", "grounding two", now=second)

    text = path.read_text()
    assert "first fact" in text
    assert "second fact" in text
    assert text.index("first fact") < text.index("second fact")


def test_read_and_clear_returns_content_and_empties_the_file(tmp_path):
    path = tmp_path / "memory_candidates.md"
    append_candidate(path, "a durable fact", "grounding", now=datetime(2026, 8, 25, 9, 0, 0, tzinfo=_IST))

    text = read_and_clear(path)

    assert "a durable fact" in text
    assert path.read_text() == ""
    # A second read finds nothing left to review.
    assert read_and_clear(path) == ""


def test_stage_memory_candidate_tool_appends_to_the_workspace_file(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    stage_tool = build_memory_candidate_tool()
    assert stage_tool.name == "stage_memory_candidate"

    result = _run(
        stage_tool.handler(
            {
                "workspace_root": str(workspace),
                "content": "User mentioned wanting more mid-cap exposure.",
                "grounding": "from this turn's discussion",
            }
        )
    )

    assert result.get("is_error") is not True
    text = (workspace / "memory_candidates.md").read_text()
    assert "User mentioned wanting more mid-cap exposure." in text
    assert "Grounding: from this turn's discussion" in text
    # Staging must never touch notes.md directly — that's the whole point.
    assert not (workspace / "notes.md").exists()


def test_stage_memory_candidate_tool_rejects_path_outside_known_roots(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()

    stage_tool = build_memory_candidate_tool()
    result = _run(
        stage_tool.handler({"workspace_root": str(outside), "content": "malicious", "grounding": "n/a"})
    )

    assert result.get("is_error") is True
    assert not (outside / "memory_candidates.md").exists()


def test_workspace_root_validation_is_shared_with_workspace_notes():
    # Review of issue #14: this used to be a third copy of the same
    # resolve-and-validate body — now both tools import the one shared
    # engine.workspace.resolve_workspace_root_arg.
    import engine.memory_candidates as memory_candidates_module
    import engine.workspace as workspace_module
    import engine.workspace_notes as workspace_notes_module

    assert memory_candidates_module._resolve_workspace_root is workspace_module.resolve_workspace_root_arg
    assert workspace_notes_module._resolve_workspace_root is workspace_module.resolve_workspace_root_arg
