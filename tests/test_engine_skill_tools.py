"""Tests for engine/skill_tools.py — turning each skill's declared
`deterministic_scripts` into typed, per-skill tool calls.

Runs the real ported scripts (red_flag_check.py, health_check.py, etc.)
through the built handler, not fakes — these scripts are pure, fast, and
fully offline, so there's no reason not to exercise the actual subprocess
path end to end.
"""

import asyncio
import json

import engine.skill_tools as skill_tools_module
from engine.skill_tools import (
    _build_argv,
    _json_schema_for_script,
    _missing_required_args,
    _resolve_workspace_root,
    build_skill_tools,
    build_skill_tools_server,
)

RED_FLAG_SCRIPT_SPEC = {
    "id": "red_flag_check",
    "path": "scripts/red_flag_check.py",
    "args": [
        {"name": "symbol", "kind": "flag", "flag": "--symbol", "required": True},
        {"name": "shareholding", "kind": "flag", "flag": "--shareholding", "required": False},
        {"name": "fundamentals", "kind": "flag", "flag": "--fundamentals", "required": False},
    ],
}

HEALTH_CHECK_SCRIPT_SPEC = {
    "id": "health_check",
    "path": "scripts/health_check.py",
    "args": [{"name": "holdings_file", "kind": "positional", "required": True}],
}


def test_json_schema_marks_only_declared_args_required():
    schema = _json_schema_for_script(RED_FLAG_SCRIPT_SPEC)
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"workspace_root", "symbol", "shareholding", "fundamentals"}
    assert schema["required"] == ["workspace_root", "symbol"]


def test_build_argv_emits_flags_only_for_provided_args():
    argv = _build_argv(RED_FLAG_SCRIPT_SPEC, {"symbol": "RELIANCE", "fundamentals": "data/f.json"})
    assert argv == ["--symbol", "RELIANCE", "--fundamentals", "data/f.json"]


def test_build_argv_emits_positional_in_declared_order():
    argv = _build_argv(HEALTH_CHECK_SCRIPT_SPEC, {"holdings_file": "data/holdings_2026-08-03.json"})
    assert argv == ["data/holdings_2026-08-03.json"]


def test_missing_required_args_flags_only_missing_required_ones():
    assert _missing_required_args(RED_FLAG_SCRIPT_SPEC, {"shareholding": "x"}) == ["symbol"]
    assert _missing_required_args(RED_FLAG_SCRIPT_SPEC, {"symbol": "RELIANCE"}) == []


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "__no_fixed_workspace__")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path)


def test_resolve_workspace_root_accepts_a_real_dir_under_a_known_root(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "test-scan"
    workspace.mkdir()
    assert _resolve_workspace_root(str(workspace)) == workspace.resolve()


def test_resolve_workspace_root_rejects_a_path_outside_known_roots(tmp_path, monkeypatch):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "__no_fixed_workspace__")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert _resolve_workspace_root(str(outside)) is None


def test_resolve_workspace_root_rejects_a_nonexistent_path(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    assert _resolve_workspace_root(str(tmp_path / "nope")) is None


def test_build_skill_tools_is_empty_for_a_skill_declaring_nothing(tmp_path, monkeypatch):
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    skill_dir = tmp_path / "quiet-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: quiet-skill\ndescription: test\n---\n")
    monkeypatch.setattr(skill_tools_module, "SKILLS_ROOT", tmp_path)

    assert build_skill_tools(["quiet-skill"]) == []
    assert build_skill_tools_server(["quiet-skill"]) is None


def test_build_skill_tools_builds_one_named_tool_per_declared_script():
    tools = build_skill_tools(["red-flag-scan"])
    assert [t.name for t in tools] == ["run_red_flag_check"]


def test_build_skill_tools_server_none_when_no_skill_declares_scripts(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_tools_module, "SKILLS_ROOT", tmp_path)
    assert build_skill_tools_server(["nonexistent"]) is None


def test_run_red_flag_check_handler_invokes_the_real_script_and_returns_its_output(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "test-scan"
    (workspace / "data").mkdir(parents=True)
    (workspace / "results").mkdir()
    fundamentals = {"source": "india_price", "as_of": "2026-08-03", "data": {"debt_to_equity": 36.65, "current_ratio": 1.2}}
    (workspace / "data" / "fundamentals_RELIANCE_2026-08-03.json").write_text(json.dumps(fundamentals))

    tools = build_skill_tools(["red-flag-scan"])
    run_tool = next(t for t in tools if t.name == "run_red_flag_check")

    result = asyncio.run(
        run_tool.handler(
            {
                "workspace_root": str(workspace),
                "symbol": "RELIANCE",
                "fundamentals": "data/fundamentals_RELIANCE_2026-08-03.json",
            }
        )
    )

    assert result.get("is_error") is not True
    text = result["content"][0]["text"]
    assert "RELIANCE" in text
    written = list((workspace / "results").glob("red_flags_RELIANCE_*.json"))
    assert len(written) == 1
    saved = json.loads(written[0].read_text())
    assert saved["symbol"] == "RELIANCE"
    assert saved["checks_performed"] == ["fundamentals_thresholds"]


def test_run_health_check_handler_invokes_the_real_script_and_writes_expected_output(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "test-scan"
    (workspace / "data").mkdir(parents=True)
    (workspace / "results").mkdir()
    holdings = [
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "average_price": 2000.0, "last_price": 2500.0}
    ]
    (workspace / "data" / "holdings_2026-08-03.json").write_text(json.dumps(holdings))

    tools = build_skill_tools(["portfolio-health-check"])
    run_tool = next(t for t in tools if t.name == "run_health_check")

    result = asyncio.run(
        run_tool.handler({"workspace_root": str(workspace), "holdings_file": "data/holdings_2026-08-03.json"})
    )

    assert result.get("is_error") is not True
    written = workspace / "results" / "health_check_2026-08-03.json"
    assert written.is_file()
    saved = json.loads(written.read_text())
    assert saved["position_count"] == 1
    assert saved["total_pnl"] == 5000.0


def test_handler_reports_missing_required_arg_without_running_anything(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "test-scan"
    workspace.mkdir()

    tools = build_skill_tools(["red-flag-scan"])
    run_tool = next(t for t in tools if t.name == "run_red_flag_check")

    result = asyncio.run(run_tool.handler({"workspace_root": str(workspace)}))

    assert result["is_error"] is True
    assert "symbol" in result["content"][0]["text"]


def test_handler_rejects_workspace_root_outside_workspaces_root(tmp_path, monkeypatch):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "__no_fixed_workspace__")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    tools = build_skill_tools(["red-flag-scan"])
    run_tool = next(t for t in tools if t.name == "run_red_flag_check")

    result = asyncio.run(run_tool.handler({"workspace_root": str(outside), "symbol": "RELIANCE"}))

    assert result["is_error"] is True
    assert "workspace_root" in result["content"][0]["text"]
