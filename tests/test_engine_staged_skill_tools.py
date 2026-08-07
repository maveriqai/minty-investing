"""Tests for `engine/staged_skill_tools.py` — builds `run_staged_<skill>`,
the dedicated in-process tool a staged skill is exposed through (see
docs/staged-skill-execution-design.md §8, candidate 3). `staged_skills`'s
own orchestration (`run_staged_skill`/`compose_and_save`) is tested
separately in tests/test_engine_staged_skills.py — these tests monkeypatch
both so a handler call here proves *wiring* (right args passed through,
right validation, right tool metadata), not orchestration correctness
again.
"""

from __future__ import annotations

import asyncio

from engine import staged_skills
from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import ToolConfig
from engine.staged_skill_tools import build_staged_workflow_tools_server
from engine.workspace import WORKSPACES_ROOT

FAKE_TOOLS = ToolConfig(mcp_servers={}, guardrail=GuardrailPolicy(), skills=["morning-digest"])


def _make_tool():
    server = build_staged_workflow_tools_server(["morning-digest"], FAKE_TOOLS)
    return server["instance"], server


def test_build_server_returns_none_for_no_staged_skills():
    assert build_staged_workflow_tools_server([], FAKE_TOOLS) is None


def test_staged_tool_is_named_and_scoped_per_skill():
    from engine.staged_skill_tools import _make_staged_tool

    built = _make_staged_tool("morning-digest", FAKE_TOOLS)
    assert built.name == "run_staged_morning_digest"
    assert built.input_schema["required"] == ["workspace_root"]


def test_staged_tool_description_includes_skill_description_and_workflow_framing():
    from engine.staged_skill_tools import _make_staged_tool

    built = _make_staged_tool("morning-digest", FAKE_TOOLS)
    assert "morning" in built.description.lower() or "digest" in built.description.lower()
    assert "Multi-stage background workflow" in built.description
    assert "Call this once" in built.description


def test_staged_tool_generalizes_to_any_stages_declaring_skill_not_just_morning_digest(tmp_path, monkeypatch):
    # docs/staged-skill-execution-design.md §10 step 3: a second, synthetic
    # skill with its own `stages` block gets a correctly named/described
    # tool from a real SKILLS_ROOT read -- nothing in _make_staged_tool is
    # keyed off the literal string "morning-digest".
    import engine.skills as skills_module
    from engine.staged_skill_tools import _make_staged_tool

    skill_dir = tmp_path / "widget-digest"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: widget-digest\ndescription: Widget-specific description text.\n"
        "stages:\n  - id: only_stage\n    instructions: do the one thing\n---\n\nBody.\n"
    )
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)

    built = _make_staged_tool("widget-digest", FAKE_TOOLS)

    assert built.name == "run_staged_widget_digest"
    assert "Widget-specific description text." in built.description
    assert "Multi-stage background workflow" in built.description


def test_staged_tool_annotations_mark_it_open_world_and_non_idempotent():
    from engine.staged_skill_tools import _make_staged_tool

    built = _make_staged_tool("morning-digest", FAKE_TOOLS)
    assert built.annotations.openWorldHint is True
    assert built.annotations.idempotentHint is False


def test_staged_tool_handler_rejects_a_workspace_root_outside_workspaces(monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    built = _make_staged_tool("morning-digest", FAKE_TOOLS)
    result = asyncio.run(built.handler({"workspace_root": "/etc"}))
    assert result["is_error"] is True
    assert str(WORKSPACES_ROOT) in result["content"][0]["text"]


def test_staged_tool_handler_calls_run_staged_skill_then_compose_and_save(tmp_path, monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    workspace_root = WORKSPACES_ROOT / "__test_staged_tool_wiring__"
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (workspace_root / "results").mkdir(parents=True, exist_ok=True)
    try:
        calls = {}

        async def fake_run_staged_skill(harness, tools, skill_body, stages, *, workspace_root, date):
            calls["run_staged_skill"] = (tools, skill_body, stages, workspace_root, date)
            return "FINAL TEXT", [("india_price", "get_quote", workspace_root / "data" / "x.json")]

        def fake_compose_and_save(final_text, all_captures, *, skill_name, workspace_root):
            calls["compose_and_save"] = (final_text, all_captures, skill_name, workspace_root)
            return "FULL TEXT WITH FOOTER"

        monkeypatch.setattr(staged_skills, "run_staged_skill", fake_run_staged_skill)
        monkeypatch.setattr(staged_skills, "compose_and_save", fake_compose_and_save)

        built = _make_staged_tool("morning-digest", FAKE_TOOLS)
        result = asyncio.run(built.handler({"workspace_root": str(workspace_root)}))

        assert result == {"content": [{"type": "text", "text": "FULL TEXT WITH FOOTER"}]}
        assert calls["run_staged_skill"][3] == workspace_root
        assert calls["compose_and_save"][2] == "morning-digest"
        assert calls["compose_and_save"][0] == "FINAL TEXT"
    finally:
        import shutil

        shutil.rmtree(workspace_root, ignore_errors=True)
