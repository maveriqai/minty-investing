"""Tests for engine/interactive.py's _save_composed_outputs — the generic
"engine writes the .md deliverable" mechanism. Staged skills must be
excluded: their own run_staged_<skill> tool handler
(engine/staged_skills.py's compose_and_save) already writes this same
file, built from every stage's actual tool calls, not just the outer
turn's own reply — this function seeing it too would silently clobber the
correct file with a worse one (issue #15).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import engine.skills as skills_module
from engine.interactive import _report_changed_files, _save_composed_outputs

_TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def _write_skill(skills_root, name, *, staged: bool):
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True)
    lines = [
        "---",
        f"name: {name}",
        "description: test skill",
        "expected_outputs:",
        f'  - "{{workspace}}/results/{name}_{{date}}.json"',
        f'  - "{{workspace}}/results/{name}_{{date}}.md"',
    ]
    if staged:
        lines += ["stages:", "  - id: only", "    instructions: do the thing"]
    lines.append("---")
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\nBody.\n")


def _patch_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path / ".claude" / "skills")


def test_save_composed_outputs_skips_a_staged_skill(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    _write_skill(tmp_path / ".claude" / "skills", "staged-skill", staged=True)
    results_dir = tmp_path / "workspace" / "results"
    results_dir.mkdir(parents=True)
    json_output = results_dir / f"staged-skill_{_TODAY}.json"
    json_output.write_text("{}")

    _save_composed_outputs(
        "outer turn's own thinner reply",
        [str(json_output)],
        ["staged-skill"],
        workspace_name="workspace",
        date=_TODAY,
    )

    assert not (results_dir / f"staged-skill_{_TODAY}.md").exists()


def test_save_composed_outputs_still_saves_a_non_staged_skill(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    _write_skill(tmp_path / ".claude" / "skills", "plain-skill", staged=False)
    results_dir = tmp_path / "workspace" / "results"
    results_dir.mkdir(parents=True)
    json_output = results_dir / f"plain-skill_{_TODAY}.json"
    json_output.write_text("{}")

    _save_composed_outputs(
        "the full composed brief",
        [str(json_output)],
        ["plain-skill"],
        workspace_name="workspace",
        date=_TODAY,
    )

    saved = results_dir / f"plain-skill_{_TODAY}.md"
    assert saved.read_text() == "the full composed brief"


def test_report_changed_files_omits_raw_data_captures_from_unmatched(tmp_path, capsys):
    # data/account_identity.json (install-wide) and workspace/data/holdings_*.json
    # (per-skill raw captures, engine/tool_capture.py) are never a skill's own
    # expected_outputs — those always live under results/ — so printing them as
    # "not matching any known skill's expected output" is misleading noise, not
    # a real signal (issue #3). Filtered out generically by directory name, not
    # by listing every known capture filename.
    identity_file = tmp_path / "data" / "account_identity.json"
    holdings_file = tmp_path / "workspace" / "data" / "holdings_2026-08-25.json"

    _report_changed_files([str(identity_file), str(holdings_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" not in out


def test_report_changed_files_still_reports_a_genuinely_unmatched_file(tmp_path, capsys):
    stray_file = tmp_path / "workspace" / "results" / "unexpected.json"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" in out
    assert str(stray_file) in out


def test_report_changed_files_reports_no_files_changed(capsys):
    _report_changed_files([], [], "workspace", date=_TODAY)

    assert capsys.readouterr().out.strip() == "[no files changed this turn]"
