"""Tests for `engine/staged_skills.py` — the engine-orchestrated stage
runner from docs/staged-skill-execution-design.md. Uses fake `Harness`/
`Session` stand-ins (same shape as tests/test_engine_session.py's
`_FakeSession`) rather than a real `claude_agent_sdk` connection — whether
a real nested session behaves this way was verified live separately (see
the design doc's §8, "Confirmed live 2026-08-07").
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from engine import staged_skills
from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import EngineResult, ToolConfig

FAKE_TOOLS = ToolConfig(mcp_servers={}, guardrail=GuardrailPolicy(), skills=["morning-digest"])


class _FakeSession:
    def __init__(self, chunks, *, captures=None, over_budget=None, raw=None):
        self._chunks = chunks
        self.last_captures = captures or []
        self.last_over_budget = over_budget or []
        self.last_result = EngineResult(ok=True, text="".join(chunks), error_kind=None, raw=raw)
        self.received_prompts: list[str] = []

    async def send(self, prompt, *, workspace_root=None):
        self.received_prompts.append(prompt)
        for chunk in self._chunks:
            yield chunk


class _FakeHarness:
    """Hands out one prepared `_FakeSession` per `open_session()` call, in
    order — records every `ToolConfig` it was opened with, so a test can
    assert on what the runner actually passed through."""

    def __init__(self, sessions: list[_FakeSession]):
        self._sessions = list(sessions)
        self.opened_tools: list[ToolConfig] = []

    def open_session(self, tools: ToolConfig):
        self.opened_tools.append(tools)
        session = self._sessions.pop(0)

        @asynccontextmanager
        async def _cm():
            yield session

        return _cm()


def _stage(id_, instructions="do the thing", **kwargs):
    return {"id": id_, "instructions": instructions, **kwargs}


def test_run_staged_skill_opens_one_fresh_session_per_stage():
    stages = [_stage("a"), _stage("b"), _stage("c")]
    sessions = [_FakeSession(["A"]), _FakeSession(["B"]), _FakeSession(["C"])]
    harness = _FakeHarness(sessions)

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "SHARED BODY", stages, workspace_root=__import__("pathlib").Path("/x"), date="2026-08-07"
        )
    )

    assert len(harness.opened_tools) == 3
    assert final_text == "C"  # only the last stage's text is the actual output
    for session in sessions:
        assert "SHARED BODY" in session.received_prompts[0]


def test_run_staged_skill_opens_stage_sessions_with_staged_tools_disabled():
    # Prevents a stage's own session from seeing run_staged_<skill> itself
    # and recursively re-triggering the whole run (§8's recursion guard).
    stages = [_stage("a")]
    harness = _FakeHarness([_FakeSession(["ok"])])

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=__import__("pathlib").Path("/x"), date="2026-08-07"
        )
    )

    assert harness.opened_tools[0].include_staged_tools is False
    assert FAKE_TOOLS.include_staged_tools is True  # the caller's own tools object is untouched


def test_run_staged_skill_concatenates_captures_across_stages():
    from pathlib import Path

    stages = [_stage("a"), _stage("b")]
    sessions = [
        _FakeSession(["A"], captures=[("india_price", "get_quote", Path("/x/data/live_quotes.json"))]),
        _FakeSession(["B"], captures=[("india_news", "get_news", Path("/x/data/news_RELIANCE.json"))]),
    ]
    harness = _FakeHarness(sessions)

    _, all_captures = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=Path("/x"), date="2026-08-07"
        )
    )

    assert len(all_captures) == 2
    assert all_captures[0][1] == "get_quote"
    assert all_captures[1][1] == "get_news"


def test_run_staged_skill_lists_a_prior_stages_missing_produces_in_the_next_prompt(tmp_path, monkeypatch):
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    (tmp_path / "workspaces" / "daily" / "results").mkdir(parents=True)

    stages = [
        # Declares produces, but the fake session never actually writes it —
        # fail-open (§9, decided 2026-08-05): recorded as failed, not raised.
        _stage("a", produces=["{workspace}/results/digest_{date}.json"]),
        _stage("b", needs=["{workspace}/results/digest_{date}.json"]),
    ]
    sessions = [_FakeSession(["A"]), _FakeSession(["B"])]
    harness = _FakeHarness(sessions)

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=tmp_path / "workspaces" / "daily", date="2026-08-07"
        )
    )

    # Stage "a" never opened, so nothing was written -> stage "b" must be
    # told the file is missing, not silently proceed as if it existed.
    second_prompt = sessions[1].received_prompts[0]
    assert "MISSING" in second_prompt
    assert "digest_2026-08-07.json" in second_prompt


def test_run_staged_skill_reports_a_present_needs_file(tmp_path, monkeypatch):
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    results_dir = tmp_path / "workspaces" / "daily" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "digest_2026-08-07.json").write_text("{}")

    stages = [_stage("b", needs=["{workspace}/results/digest_{date}.json"])]
    session = _FakeSession(["ok"])
    harness = _FakeHarness([session])

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=results_dir.parent, date="2026-08-07"
        )
    )

    assert "present" in session.received_prompts[0]
    assert "digest_2026-08-07.json" in session.received_prompts[0]


def test_run_staged_skill_prints_per_stage_and_total_diagnostics(capsys):
    stages = [_stage("a"), _stage("b")]
    raw = SimpleNamespace(duration_ms=1500, total_cost_usd=0.05, usage={"input_tokens": 10, "output_tokens": 5})
    sessions = [_FakeSession(["A"], raw=raw), _FakeSession(["B"], raw=raw)]
    harness = _FakeHarness(sessions)

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=__import__("pathlib").Path("/x"), date="2026-08-07"
        )
    )

    out = capsys.readouterr().out
    assert "[stage] a: ok" in out
    assert "[stage] b: ok" in out
    assert "[staged run total]" in out
    assert "3.0s" in out  # 1.5s + 1.5s
    assert "$0.1000" in out  # 0.05 + 0.05


def test_compose_and_save_writes_footer_and_md_output(tmp_path, monkeypatch):
    import engine.skills as skills_module

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "morning-digest"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: morning-digest\ndescription: test\n'
        'expected_outputs:\n  - "{workspace}/results/digest_{date}.md"\n---\n'
    )
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", skills_root)

    workspace_root = tmp_path / "workspaces" / "daily"
    (workspace_root / "results").mkdir(parents=True)
    (workspace_root / "data").mkdir(parents=True)


    from engine.tool_capture import today_ist

    full_text = staged_skills.compose_and_save(
        "# Digest\nAll good.",
        [("india_price", "get_quote", workspace_root / "data" / "live_quotes.json")],
        skill_name="morning-digest",
        workspace_root=workspace_root,
    )

    assert "Sources" in full_text
    saved = workspace_root / "results" / f"digest_{today_ist()}.md"
    assert saved.read_text() == full_text


def test_compose_and_save_skips_footer_when_final_text_already_has_the_disclaimer(tmp_path, monkeypatch):
    """The compose stage's own SKILL.md instructions say not to write a
    closing footer/disclaimer (issue #27) — but that's prose, not reliably
    followed (issue #31). If the compose stage wrote one anyway, appending
    the real one on top would be the exact visible duplicate #27 is about."""
    import engine.skills as skills_module
    from engine.sources_footer import DISCLAIMER

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "morning-digest"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: morning-digest\ndescription: test\n'
        'expected_outputs:\n  - "{workspace}/results/digest_{date}.md"\n---\n'
    )
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", skills_root)

    workspace_root = tmp_path / "workspaces" / "daily"
    (workspace_root / "results").mkdir(parents=True)
    (workspace_root / "data").mkdir(parents=True)

    final_text = f"# Digest\nAll good.\n\n---\n{DISCLAIMER}\n"
    full_text = staged_skills.compose_and_save(
        final_text,
        [("india_price", "get_quote", workspace_root / "data" / "live_quotes.json")],
        skill_name="morning-digest",
        workspace_root=workspace_root,
    )

    assert full_text == final_text
    assert full_text.count(DISCLAIMER) == 1
    assert "**Sources**" not in full_text


def test_compose_and_save_is_a_noop_when_final_text_is_blank(tmp_path, monkeypatch):
    import engine.skills as skills_module

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "morning-digest"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: morning-digest\ndescription: test\n'
        'expected_outputs:\n  - "{workspace}/results/digest_{date}.md"\n---\n'
    )
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", skills_root)

    workspace_root = tmp_path / "workspaces" / "daily"
    (workspace_root / "results").mkdir(parents=True)

    staged_skills.compose_and_save("", [], skill_name="morning-digest", workspace_root=workspace_root)

    assert list((workspace_root / "results").iterdir()) == []


def test_run_staged_skill_injects_the_active_workspace_note_into_each_stage_prompt():
    # Review of issue #14: a stage nudged by the always-on
    # update_workspace_notes/stage_memory_candidate system-prompt
    # instructions has no reliable workspace_root to cite unless the
    # stage's own prompt carries the same "[Active workspace: ...]" note
    # engine/interactive.py's _run_turn already gives every other turn.
    from pathlib import Path

    stages = [_stage("a")]
    session = _FakeSession(["ok"])
    harness = _FakeHarness([session])
    workspace_root = Path("/real/workspace")

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "SHARED BODY", stages, workspace_root=workspace_root, date="2026-08-07"
        )
    )

    sent = session.received_prompts[0]
    assert "[Active workspace: /real/workspace" in sent
    assert "SHARED BODY" in sent
