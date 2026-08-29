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
import json

from engine import identity_check, staged_skills
from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import ToolConfig
from engine.staged_skill_tools import build_staged_workflow_tools_server
from engine.workspace import DEV_WORKSPACES_ROOT, WORKSPACE_ROOT

FAKE_TOOLS = ToolConfig(mcp_servers={}, guardrail=GuardrailPolicy(), skills=["morning-digest"])


def _make_tool():
    server = build_staged_workflow_tools_server(["morning-digest"], FAKE_TOOLS)
    return server["instance"], server


def _precheck_result(status: str, *, anchor_user_id="ANCHOR", live_user_id="LIVE", is_error=False) -> dict:
    """Same dict shape identity_check.py's own _build_handler returns —
    {"content": [{"type": "text", "text": ...}]}, optionally with
    "is_error": True — since the real precheck call site (issue #51,
    engine/staged_skill_tools.py) reads that shape directly off
    build_identity_check_tool(...).handler({})'s return value."""
    payload = json.dumps({"status": status, "anchor_user_id": anchor_user_id, "live_user_id": live_user_id})
    result = {"content": [{"type": "text", "text": payload}]}
    if is_error:
        result["is_error"] = True
    return result


class _FakePrecheckTool:
    """Stands in for identity_check.build_identity_check_tool(...)'s
    return value — an SdkMcpTool, whose .handler is the awaitable the real
    call site (engine/staged_skill_tools.py) invokes directly with {}."""

    def __init__(self, result: dict, calls: list) -> None:
        self._result = result
        self._calls = calls

    async def handler(self, args: dict) -> dict:
        self._calls.append(args)
        return self._result


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


def test_staged_tool_handler_rejects_a_workspace_root_outside_known_roots(monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    built = _make_staged_tool("morning-digest", FAKE_TOOLS)
    result = asyncio.run(built.handler({"workspace_root": "/etc"}))
    assert result["is_error"] is True
    assert str(WORKSPACE_ROOT) in result["content"][0]["text"]


def test_staged_tool_handler_calls_run_staged_skill_then_compose_and_save(tmp_path, monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    workspace_root = DEV_WORKSPACES_ROOT / "__test_staged_tool_wiring__"
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
        # morning-digest declares identity_precheck: true (issue #51) — a
        # real check_identity_match call would hit a real Kite session, so
        # this must be stubbed even though this test isn't about the
        # precheck itself, to stay hermetic.
        monkeypatch.setattr(
            identity_check,
            "build_identity_check_tool",
            lambda state: _FakePrecheckTool(_precheck_result("match"), []),
        )

        built = _make_staged_tool("morning-digest", FAKE_TOOLS)
        result = asyncio.run(built.handler({"workspace_root": str(workspace_root)}))

        assert result == {"content": [{"type": "text", "text": "FULL TEXT WITH FOOTER"}]}
        assert calls["run_staged_skill"][3] == workspace_root
        assert calls["compose_and_save"][2] == "morning-digest"
        assert calls["compose_and_save"][0] == "FINAL TEXT"
    finally:
        import shutil

        shutil.rmtree(workspace_root, ignore_errors=True)


def test_staged_tool_identity_precheck_mismatch_short_circuits_before_any_stage(tmp_path, monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    workspace_root = DEV_WORKSPACES_ROOT / "__test_staged_tool_precheck_mismatch__"
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (workspace_root / "results").mkdir(parents=True, exist_ok=True)
    try:
        calls: list = []

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("run_staged_skill must not run after a confirmed identity mismatch")

        monkeypatch.setattr(staged_skills, "run_staged_skill", fail_if_called)
        monkeypatch.setattr(
            identity_check,
            "build_identity_check_tool",
            lambda state: _FakePrecheckTool(
                _precheck_result("mismatch", anchor_user_id="QK0438", live_user_id="BOGUS999"), calls
            ),
        )

        built = _make_staged_tool("morning-digest", FAKE_TOOLS)
        result = asyncio.run(built.handler({"workspace_root": str(workspace_root)}))

        assert len(calls) == 1
        assert calls[0] == {}
        assert result.keys() == {"content"}  # plain reply, not an error envelope
        text = result["content"][0]["text"]
        assert "QK0438" in text
        assert "BOGUS999" in text
    finally:
        import shutil

        shutil.rmtree(workspace_root, ignore_errors=True)


def test_staged_tool_identity_precheck_non_mismatch_falls_through(tmp_path, monkeypatch):
    from engine.staged_skill_tools import _make_staged_tool

    workspace_root = DEV_WORKSPACES_ROOT / "__test_staged_tool_precheck_fallthrough__"
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (workspace_root / "results").mkdir(parents=True, exist_ok=True)
    try:
        for status, is_error in [("match", False), ("no_anchor", False), ("error", True)]:
            calls: list = []
            ran = {}

            async def fake_run_staged_skill(harness, tools, skill_body, stages, *, workspace_root, date, ran=ran):
                ran["called"] = True
                return "FINAL TEXT", []

            def fake_compose_and_save(final_text, all_captures, *, skill_name, workspace_root):
                return "FULL TEXT"

            monkeypatch.setattr(staged_skills, "run_staged_skill", fake_run_staged_skill)
            monkeypatch.setattr(staged_skills, "compose_and_save", fake_compose_and_save)
            monkeypatch.setattr(
                identity_check,
                "build_identity_check_tool",
                lambda state, status=status, is_error=is_error, calls=calls: _FakePrecheckTool(
                    _precheck_result(status, is_error=is_error), calls
                ),
            )

            built = _make_staged_tool("morning-digest", FAKE_TOOLS)
            result = asyncio.run(built.handler({"workspace_root": str(workspace_root)}))

            assert ran.get("called") is True, f"status={status!r} should fall through to run_staged_skill"
            assert result == {"content": [{"type": "text", "text": "FULL TEXT"}]}
    finally:
        import shutil

        shutil.rmtree(workspace_root, ignore_errors=True)


def test_staged_tool_without_identity_precheck_never_calls_it(tmp_path, monkeypatch):
    # docs/staged-skill-execution-design.md §8's 2026-08-29 #51 revision:
    # identity_precheck is opt-in — a skill that doesn't declare it must
    # never spend the precheck call at all.
    import engine.skills as skills_module
    from engine.staged_skill_tools import _make_staged_tool

    skill_dir = tmp_path / "widget-digest"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: widget-digest\ndescription: Widget-specific description text.\n"
        "stages:\n  - id: only_stage\n    instructions: do the one thing\n---\n\nBody.\n"
    )
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)

    workspace_root = DEV_WORKSPACES_ROOT / "__test_staged_tool_no_precheck__"
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    (workspace_root / "results").mkdir(parents=True, exist_ok=True)
    try:

        def fail_if_called(state):
            raise AssertionError("build_identity_check_tool must not be called when identity_precheck is unset")

        async def fake_run_staged_skill(harness, tools, skill_body, stages, *, workspace_root, date):
            return "FINAL TEXT", []

        def fake_compose_and_save(final_text, all_captures, *, skill_name, workspace_root):
            return "FULL TEXT"

        monkeypatch.setattr(identity_check, "build_identity_check_tool", fail_if_called)
        monkeypatch.setattr(staged_skills, "run_staged_skill", fake_run_staged_skill)
        monkeypatch.setattr(staged_skills, "compose_and_save", fake_compose_and_save)

        built = _make_staged_tool("widget-digest", FAKE_TOOLS)
        result = asyncio.run(built.handler({"workspace_root": str(workspace_root)}))

        assert result == {"content": [{"type": "text", "text": "FULL TEXT"}]}
    finally:
        import shutil

        shutil.rmtree(workspace_root, ignore_errors=True)
