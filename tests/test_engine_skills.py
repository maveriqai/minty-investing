"""Tests for engine/skills.py — declarative per-skill expected-output
patterns and the generic matcher, built so adding a skill costs one
frontmatter field, not per-skill Python orchestration.
"""

from pathlib import Path

import engine.skills as skills_module
from engine.skills import (
    load_expected_outputs,
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
