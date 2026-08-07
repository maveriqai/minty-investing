"""Tests for engine/tool_budget.py — per-turn tool-call counting against a
skill's own declared budget, for audit purposes only. Never denies a call
— see the module's own docstring for why a hard PreToolUse deny was tried
and dropped."""

from pathlib import Path

import engine.skills as skills_module
from engine.tool_budget import TurnBudgetTracker, build_budget_tracker


def _write_skill(root: Path, name: str, frontmatter_body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter_body}\n---\n\n# {name}\n")


def test_record_never_raises_or_blocks_regardless_of_count():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 1})
    for _ in range(50):
        tracker.record("mcp__india_news__get_news")  # no exception, no return value to check


def test_over_budget_empty_when_nothing_recorded():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 5})
    assert tracker.over_budget() == []


def test_over_budget_empty_while_under_the_declared_limit():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 5})
    for _ in range(5):
        tracker.record("mcp__india_news__get_news")
    assert tracker.over_budget() == []


def test_over_budget_reports_the_tool_and_actual_count_once_exceeded():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 2})
    for _ in range(5):
        tracker.record("mcp__india_news__get_news")

    lines = tracker.over_budget()

    assert len(lines) == 1
    assert "india_news.get_news" in lines[0]
    assert "5 times" in lines[0]
    assert "ceiling of 2" in lines[0]


def test_reset_clears_counts_for_a_new_turn():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 1})
    tracker.record("mcp__india_news__get_news")
    tracker.record("mcp__india_news__get_news")
    assert tracker.over_budget() != []

    tracker.reset()

    assert tracker.over_budget() == []


def test_record_ignores_tools_with_no_declared_budget():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 1})
    for _ in range(50):
        tracker.record("mcp__india_price__get_quote")
    assert tracker.over_budget() == []


def test_record_ignores_non_mcp_namespaced_tools():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 0})
    tracker.record("Bash")
    tracker.record("Read")
    assert tracker.over_budget() == []


def test_build_budget_tracker_reads_a_skills_declared_budgets(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "morning-digest",
        "name: morning-digest\ndescription: test\n"
        "tool_call_budgets:\n"
        "  india_news.get_news: 3",
    )

    tracker = build_budget_tracker(["morning-digest"])
    for _ in range(4):
        tracker.record("mcp__india_news__get_news")

    assert len(tracker.over_budget()) == 1


def test_build_budget_tracker_merges_across_multiple_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(
        tmp_path,
        "morning-digest",
        "name: morning-digest\ndescription: test\ntool_call_budgets:\n  india_news.get_news: 3",
    )
    _write_skill(
        tmp_path,
        "red-flag-scan",
        "name: red-flag-scan\ndescription: test\ntool_call_budgets:\n  india_filings.get_announcements: 5",
    )

    tracker = build_budget_tracker(["morning-digest", "red-flag-scan"])

    assert tracker._budgets == {
        ("india_news", "get_news"): 3,
        ("india_filings", "get_announcements"): 5,
    }


def test_build_budget_tracker_empty_when_no_skill_declares_budgets(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)
    _write_skill(tmp_path, "quiet-skill", "name: quiet-skill\ndescription: test")

    tracker = build_budget_tracker(["quiet-skill"])
    tracker.record("mcp__india_news__get_news")

    assert tracker.over_budget() == []
