"""Tests for engine/skills.py — declarative per-skill expected-output
patterns and the generic matcher, built so adding a skill costs one
frontmatter field, not per-skill Python orchestration.
"""

from pathlib import Path

import pytest

import engine.skills as skills_module
from engine.skills import (
    composed_output_patterns,
    load_deterministic_scripts,
    load_expected_outputs,
    load_identity_precheck,
    load_stages,
    load_tool_call_budgets,
    match_changed_files,
    resolve_pattern,
)


def _write_skill(root: Path, name: str, frontmatter_body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter_body}\n---\n\n# {name}\n")


def test_load_expected_outputs_reads_declared_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "red-flag-scan",
        'name: red-flag-scan\ndescription: test\nexpected_outputs:\n  - "workspaces/{workspace}/results/red_flags_*_{date}.json"',
    )

    assert load_expected_outputs("red-flag-scan") == [
        "workspaces/{workspace}/results/red_flags_*_{date}.json"
    ]


def test_load_expected_outputs_empty_when_skill_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "no-outputs", "name: no-outputs\ndescription: test")

    assert load_expected_outputs("no-outputs") == []


def test_load_expected_outputs_empty_when_skill_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    assert load_expected_outputs("nonexistent") == []


def test_load_deterministic_scripts_reads_declared_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "red-flag-scan",
        "name: red-flag-scan\ndescription: test\n"
        "deterministic_scripts:\n"
        "  - id: red_flag_check\n"
        "    path: scripts/red_flag_check.py\n"
        "    args:\n"
        "      - {name: symbol, kind: flag, flag: \"--symbol\", required: true}",
    )

    scripts = load_deterministic_scripts("red-flag-scan")

    assert scripts == [
        {
            "id": "red_flag_check",
            "path": "scripts/red_flag_check.py",
            "args": [{"name": "symbol", "kind": "flag", "flag": "--symbol", "required": True}],
        }
    ]


def test_load_deterministic_scripts_empty_when_skill_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "no-scripts", "name: no-scripts\ndescription: test")

    assert load_deterministic_scripts("no-scripts") == []


def test_load_deterministic_scripts_empty_when_skill_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    assert load_deterministic_scripts("nonexistent") == []


def test_resolve_pattern_substitutes_date_always():
    assert resolve_pattern("results/digest_{date}.json", workspace_name=None, date="2026-08-03") == (
        "results/digest_2026-08-03.json"
    )


def test_resolve_pattern_substitutes_workspace_when_given():
    resolved = resolve_pattern(
        "workspaces/{workspace}/results/health_check_{date}.json",
        workspace_name="test-scan",
        date="2026-08-03",
    )
    assert resolved == "workspaces/test-scan/results/health_check_2026-08-03.json"


def test_resolve_pattern_leaves_workspace_placeholder_when_none_active():
    resolved = resolve_pattern(
        "workspaces/{workspace}/results/health_check_{date}.json", workspace_name=None, date="2026-08-03"
    )
    assert "{workspace}" in resolved


def test_match_changed_files_finds_a_real_match(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path / ".claude" / "skills")
    _write_skill(
        tmp_path / ".claude" / "skills",
        "red-flag-scan",
        'name: red-flag-scan\ndescription: test\nexpected_outputs:\n  - "workspaces/{workspace}/results/red_flags_*_{date}.json"',
    )
    result_file = tmp_path / "workspaces" / "test-scan" / "results" / "red_flags_RELIANCE_2026-08-03.json"
    result_file.parent.mkdir(parents=True)
    result_file.write_text("{}")

    changed = [str(result_file), str(tmp_path / "unrelated.txt")]
    matches = match_changed_files(
        "red-flag-scan", changed, workspace_name="test-scan", date="2026-08-03"
    )

    assert matches == [str(result_file)]


def test_match_changed_files_empty_when_pattern_needs_workspace_but_none_active(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path / ".claude" / "skills")
    _write_skill(
        tmp_path / ".claude" / "skills",
        "red-flag-scan",
        'name: red-flag-scan\ndescription: test\nexpected_outputs:\n  - "workspaces/{workspace}/results/red_flags_*_{date}.json"',
    )

    matches = match_changed_files(
        "red-flag-scan", ["anything"], workspace_name=None, date="2026-08-03"
    )
    assert matches == []


def test_match_changed_files_empty_when_skill_declares_no_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path / ".claude" / "skills")
    _write_skill(tmp_path / ".claude" / "skills", "quiet-skill", "name: quiet-skill\ndescription: test")

    matches = match_changed_files("quiet-skill", ["anything"], workspace_name=None, date="2026-08-03")
    assert matches == []


def test_composed_output_patterns_returns_only_the_md_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "morning-digest",
        "name: morning-digest\ndescription: test\n"
        "expected_outputs:\n"
        '  - "workspaces/{workspace}/results/digest_{date}.json"\n'
        '  - "workspaces/{workspace}/results/digest_{date}.md"',
    )

    assert composed_output_patterns("morning-digest") == [
        "workspaces/{workspace}/results/digest_{date}.md"
    ]


def test_composed_output_patterns_empty_when_skill_declares_no_md_output(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "red-flag-scan",
        'name: red-flag-scan\ndescription: test\nexpected_outputs:\n  - "workspaces/{workspace}/results/red_flags_*_{date}.json"',
    )

    assert composed_output_patterns("red-flag-scan") == []


def test_load_tool_call_budgets_reads_declared_ceilings(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "morning-digest",
        "name: morning-digest\ndescription: test\ntool_call_budgets:\n  india_news.get_news: 25",
    )

    assert load_tool_call_budgets("morning-digest") == {"india_news.get_news": 25}


def test_load_tool_call_budgets_empty_when_skill_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "no-budgets", "name: no-budgets\ndescription: test")

    assert load_tool_call_budgets("no-budgets") == {}


def test_load_tool_call_budgets_empty_when_skill_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    assert load_tool_call_budgets("nonexistent") == {}


def test_load_identity_precheck_true_when_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "morning-digest", "name: morning-digest\ndescription: test\nidentity_precheck: true")

    assert load_identity_precheck("morning-digest") is True


def test_load_identity_precheck_false_when_skill_declares_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "no-precheck", "name: no-precheck\ndescription: test")

    assert load_identity_precheck("no-precheck") is False


def test_load_identity_precheck_false_when_skill_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    assert load_identity_precheck("nonexistent") is False


def test_thesis_tracker_declares_its_per_symbol_theses_output():
    # Issue #44: workspace/theses/<SYMBOL>.md — CLAUDE.md's own documented
    # "one per-symbol exception" thesis-tracker writes — used to be absent
    # from expected_outputs entirely, so a correct run got its own output
    # flagged as unmatched by _report_changed_files. Reads the real,
    # unmonkeypatched .claude/skills/thesis-tracker/SKILL.md.
    assert "{workspace}/theses/*.md" in load_expected_outputs("thesis-tracker")


def test_thesis_tracker_theses_pattern_matches_a_real_per_symbol_file(tmp_path, monkeypatch):
    # SKILLS_ROOT stays real (thesis-tracker's actual SKILL.md), only
    # REPO_ROOT is redirected — match_changed_files globs REPO_ROOT for
    # the resolved pattern, and this proves the new bare "*.md" pattern
    # (no {symbol} placeholder needed) actually matches a real per-symbol
    # filename on disk, not just that the string is declared.
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    theses_file = tmp_path / "workspace" / "theses" / "HEROMOTOCO.md"
    theses_file.parent.mkdir(parents=True)
    theses_file.write_text("thesis body")

    matches = match_changed_files(
        "thesis-tracker", [str(theses_file)], workspace_name="workspace", date="2026-08-28"
    )

    assert matches == [str(theses_file)]


def test_load_stages_rejects_a_needs_file_only_a_later_stage_produces(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "bad-order",
        "name: bad-order\ndescription: test\n"
        "stages:\n"
        "  - id: a\n"
        "    instructions: do a\n"
        '    needs: ["{workspace}/results/x.json"]\n'
        "  - id: b\n"
        "    instructions: do b\n"
        '    produces: ["{workspace}/results/x.json"]\n',
    )

    with pytest.raises(ValueError, match="same-or-later stage"):
        load_stages("bad-order")


def test_load_stages_rejects_a_critical_stage_with_no_produces(tmp_path, monkeypatch):
    # Issue #52: run_staged_skill's abort check only fires off a stage's
    # own `produces` glob check — a `critical` stage with nothing declared
    # there would silently never abort, defeating the point of the flag.
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "critical-no-produces",
        "name: critical-no-produces\ndescription: test\n"
        "stages:\n"
        "  - id: a\n"
        "    instructions: do a\n"
        "    critical: true\n",
    )

    with pytest.raises(ValueError, match="critical"):
        load_stages("critical-no-produces")


def test_load_stages_accepts_a_critical_stage_with_produces(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "critical-with-produces",
        "name: critical-with-produces\ndescription: test\n"
        "stages:\n"
        "  - id: a\n"
        "    instructions: do a\n"
        "    critical: true\n"
        '    produces: ["{workspace}/results/x.json"]\n',
    )

    stages = load_stages("critical-with-produces")

    assert stages[0]["critical"] is True
