"""Tests for `engine/staged_skills.py` — the engine-orchestrated stage
runner from docs/staged-skill-execution-design.md. Uses fake `Harness`/
`Session` stand-ins (same shape as tests/test_engine_session.py's
`_FakeSession`) rather than a real `claude_agent_sdk` connection — whether
a real nested session behaves this way was verified live separately (see
the design doc's §8, "Confirmed live 2026-08-07").
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from engine import staged_skills
from engine.guardrail import GuardrailPolicy
from engine.harnesses.base import EngineResult, ToolConfig

FAKE_TOOLS = ToolConfig(mcp_servers={}, guardrail=GuardrailPolicy(), skills=["morning-digest"])


class _FakeSession:
    def __init__(self, chunks, *, captures=None, over_budget=None, raw=None, tool_calls=None):
        self._chunks = chunks
        self.last_captures = captures or []
        self.last_over_budget = over_budget or []
        self.last_tool_calls = tool_calls or []
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


def test_run_staged_skill_writes_each_stages_tool_calls_to_its_own_audit_log(tmp_path):
    """Issue #47's audit log used to silently drop every staged run's
    per-stage tool calls — live-observed 2026-08-29, a real deliberate
    account-mismatch test left no way to confirm whether a given stage had
    even attempted the identity check. Each stage's `session.last_tool_calls`
    must now land in its own sessions/*_tool_calls.jsonl file, same as a
    single-shot ClaudeAgentSDKHarness.run() call already gets."""
    stages = [_stage("a"), _stage("b")]
    sessions = [
        _FakeSession(["A"], tool_calls=[{"tool_name": "mcp__identity_check__check_identity_match"}]),
        _FakeSession(["B"], tool_calls=[{"tool_name": "mcp__fetch_holdings__fetch_holdings"}]),
    ]
    harness = _FakeHarness(sessions)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-07"
        )
    )

    # Named by each stage's own start time (same convention as a
    # single-shot ClaudeAgentSDKHarness.run() call) — in this fake,
    # instant-running harness both stages can legitimately land the same
    # second-granularity timestamp and share one file; a real run with
    # stages seconds apart would produce separate files. Either way, every
    # stage's tool calls must be recoverable, in order.
    audit_logs = sorted((workspace_root / "sessions").glob("*_tool_calls.jsonl"))
    assert len(audit_logs) >= 1
    logged_tool_names = [
        json.loads(line)["tool_name"] for path in audit_logs for line in path.read_text().splitlines()
    ]
    assert logged_tool_names == [
        "mcp__identity_check__check_identity_match",
        "mcp__fetch_holdings__fetch_holdings",
    ]


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

    # Fixed clock, set well *after* the file above was written, so a file
    # genuinely written before this run started (simulating "an earlier
    # stage in this same run already produced it") reads as fresh — not
    # dependent on real wall-clock timing (issue #52's freshness check).
    asyncio.run(
        staged_skills.run_staged_skill(
            harness,
            FAKE_TOOLS,
            "body",
            stages,
            workspace_root=results_dir.parent,
            date="2026-08-07",
            now=lambda: (results_dir / "digest_2026-08-07.json").stat().st_mtime + 0.5,
        )
    )

    assert "present" in session.received_prompts[0]
    assert "digest_2026-08-07.json" in session.received_prompts[0]


def test_run_staged_skill_treats_a_stale_needs_file_as_missing(tmp_path, monkeypatch):
    """Issue #52: a `needs`/`produces` file's mere existence isn't enough —
    a file left over from a legitimately earlier run that same day must not
    be mistaken for this run's own output. Live-observed 2026-08-29: a
    stage that correctly refused to write fresh output (an account-identity
    mismatch) was still treated as having succeeded, because an hours-old
    file from an earlier run happened to already be sitting there."""
    import os

    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    results_dir = tmp_path / "workspaces" / "daily" / "results"
    results_dir.mkdir(parents=True)
    stale_file = results_dir / "digest_2026-08-07.json"
    stale_file.write_text("{}")
    stale_mtime = stale_file.stat().st_mtime
    os.utime(stale_file, (stale_mtime - 3600, stale_mtime - 3600))  # an hour "before this run"

    stages = [_stage("b", needs=["{workspace}/results/digest_{date}.json"])]
    session = _FakeSession(["ok"])
    harness = _FakeHarness([session])

    asyncio.run(
        staged_skills.run_staged_skill(
            harness,
            FAKE_TOOLS,
            "body",
            stages,
            workspace_root=results_dir.parent,
            date="2026-08-07",
            now=lambda: stale_mtime,  # "this run" started after the stale file's real mtime
        )
    )

    assert "MISSING" in session.received_prompts[0]
    assert "digest_2026-08-07.json" in session.received_prompts[0]


def test_run_staged_skill_aborts_after_a_critical_stages_produces_check_fails(tmp_path, monkeypatch):
    """Issue #52: a stage marked `critical: true` whose declared `produces`
    file never lands must abort the run right there — no later stage runs,
    and the failing stage's own text (not a later stage's, which never
    executes) is what the caller gets back."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    (tmp_path / "workspaces" / "daily" / "results").mkdir(parents=True)

    stages = [
        _stage(
            "a",
            instructions="do stage a",
            critical=True,
            produces=["{workspace}/results/digest_{date}.json"],
        ),
        _stage("b", instructions="do stage b"),
    ]
    sessions = [_FakeSession(["I have to stop here — account mismatch."]), _FakeSession(["never runs"])]
    harness = _FakeHarness(sessions)

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness,
            FAKE_TOOLS,
            "body",
            stages,
            workspace_root=tmp_path / "workspaces" / "daily",
            date="2026-08-07",
        )
    )

    assert len(harness.opened_tools) == 1  # stage "b" never opened
    assert final_text == "I have to stop here — account mismatch."


def test_run_staged_skill_does_not_abort_when_a_non_critical_stage_fails(tmp_path, monkeypatch):
    """Regression guard: a stage without `critical: true` whose `produces`
    file doesn't land must still fail open — the existing 2026-08-05
    decision, unchanged by #52's critical-stage addition."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    (tmp_path / "workspaces" / "daily" / "results").mkdir(parents=True)

    stages = [
        _stage("a", produces=["{workspace}/results/digest_{date}.json"]),
        _stage("b", needs=["{workspace}/results/digest_{date}.json"]),
    ]
    sessions = [_FakeSession(["A"]), _FakeSession(["B"])]
    harness = _FakeHarness(sessions)

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness,
            FAKE_TOOLS,
            "body",
            stages,
            workspace_root=tmp_path / "workspaces" / "daily",
            date="2026-08-07",
        )
    )

    assert len(harness.opened_tools) == 2  # stage "b" still ran
    assert final_text == "B"


class _RaisingFakeSession:
    """A session whose `send()` raises partway through streaming — a stage
    hitting a real error (network failure, unhandled exception) rather than
    just silently not writing its `produces` files."""

    def __init__(self):
        self.last_captures = []
        self.last_over_budget = []
        self.last_tool_calls = []
        self.last_result = EngineResult(ok=False, text="", error_kind="exception", raw=None)
        self.received_prompts: list[str] = []

    async def send(self, prompt, *, workspace_root=None):
        self.received_prompts.append(prompt)
        raise RuntimeError("boom")
        yield ""  # pragma: no cover - unreachable, makes this an async generator


def test_run_staged_skill_treats_a_raised_exception_as_stage_failure(tmp_path, monkeypatch):
    """Issue #52: docs/staged-skill-execution-design.md §9 documented a
    raised exception as already being treated like a missing `produces`
    file, but the loop had no try/except — the exception propagated and
    would have crashed the whole staged run. Must degrade gracefully
    instead, whether or not the stage is critical."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    (tmp_path / "workspaces" / "daily" / "results").mkdir(parents=True)

    stages = [
        _stage("a", produces=["{workspace}/results/digest_{date}.json"]),
        _stage("b"),
    ]
    harness = _FakeHarness([_RaisingFakeSession(), _FakeSession(["B"])])

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness,
            FAKE_TOOLS,
            "body",
            stages,
            workspace_root=tmp_path / "workspaces" / "daily",
            date="2026-08-07",
        )
    )

    # Not critical -> fails open, stage "b" still runs and its text wins.
    assert len(harness.opened_tools) == 2
    assert final_text == "B"


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


def _write_plan_file(workspace_root, filename, angles):
    data_dir = workspace_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    plan = {"request": "test request", "already_known": [], "angles": angles}
    (data_dir / filename).write_text(json.dumps(plan))
    return data_dir / filename


def _dynamic_stage(id_="gather", max_instances=6, **kwargs):
    return {
        "id": id_,
        "dynamic": True,
        "needs": ["{workspace}/data/research_plan_*_{date}.json"],
        "produces": ["{workspace}/data/research_finding_*_{date}.json"],
        "max_instances": max_instances,
        **kwargs,
    }


def test_run_staged_skill_expands_a_dynamic_stage_into_one_instance_per_angle(tmp_path, monkeypatch):
    """docs/research-discovery-plan.md §4 — a `dynamic: true` stage reads
    the plan file its own `needs` points at and runs one fresh stage
    session per angle, each through the identical execution path an
    ordinary declared stage uses."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)
    _write_plan_file(
        workspace_root,
        "research_plan_pli-semis_2026-08-30.json",
        [
            {"id": "policy", "question": "What did the new tranche fund?", "tool_hint": "india_news.get_news"},
            {"id": "names", "question": "Which listed names are exposed?"},
        ],
    )

    stages = [_dynamic_stage()]
    sessions = [_FakeSession(["policy finding"]), _FakeSession(["names finding"])]
    harness = _FakeHarness(sessions)

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )

    assert len(harness.opened_tools) == 2
    assert "policy" in sessions[0].received_prompts[0]
    assert "What did the new tranche fund?" in sessions[0].received_prompts[0]
    assert "india_news.get_news" in sessions[0].received_prompts[0]
    assert "names" in sessions[1].received_prompts[0]
    assert "Which listed names are exposed?" in sessions[1].received_prompts[0]
    # Issue #61 — the generated instruction must route through
    # update_workspace_notes, not the raw Write tool (removed by #55, and
    # never wired into this instruction's own rewrite until this fix).
    assert "update_workspace_notes" in sessions[0].received_prompts[0]
    assert "Write your finding" not in sessions[0].received_prompts[0]
    assert "research_finding_policy_{date}.json" in sessions[0].received_prompts[0]


def test_run_staged_skill_caps_dynamic_expansion_at_max_instances(tmp_path, monkeypatch):
    """`open_deep_research`'s own `max_concurrent_research_units` slicing
    is the direct precedent (docs/research-discovery-plan.md §4) — a hard,
    orchestrator-enforced cap, independent of how many angles the plan
    file itself claims."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)
    angles = [{"id": f"angle{i}", "question": f"q{i}"} for i in range(8)]
    _write_plan_file(workspace_root, "research_plan_wide_2026-08-30.json", angles)

    stages = [_dynamic_stage(max_instances=3)]
    sessions = [_FakeSession(["a"]), _FakeSession(["b"]), _FakeSession(["c"])]
    harness = _FakeHarness(sessions)

    asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )

    # Capped at 3 — only 3 sessions provided, so a 4th open_session call
    # would have raised (IndexError popping an empty list) had the cap not
    # been enforced.
    assert len(harness.opened_tools) == 3


def test_run_staged_skill_dynamic_stage_with_missing_plan_file_expands_to_nothing(tmp_path, monkeypatch):
    """No plan file (research-discovery never ran, or hasn't written it
    yet) means zero instances to run — fail-open, not a crash, and a fixed
    later stage (synthesize) still runs."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)

    stages = [_dynamic_stage(), _stage("synthesize")]
    sessions = [_FakeSession(["synth text"])]  # only synthesize should open a session
    harness = _FakeHarness(sessions)

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )

    assert len(harness.opened_tools) == 1
    assert final_text == "synth text"


def test_run_staged_skill_dynamic_stage_with_malformed_plan_file_expands_to_nothing(tmp_path, monkeypatch):
    """A plan file that exists but isn't valid JSON must degrade the same
    way a missing one does — no instances, no crash — not propagate a
    JSONDecodeError up through the whole staged run."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)
    data_dir = workspace_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "research_plan_bad_2026-08-30.json").write_text("not valid json")

    stages = [_dynamic_stage(), _stage("synthesize")]
    sessions = [_FakeSession(["synth text"])]
    harness = _FakeHarness(sessions)

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )

    assert len(harness.opened_tools) == 1
    assert final_text == "synth text"


def test_run_staged_skill_one_failed_gather_instance_does_not_stop_synthesize(tmp_path, monkeypatch):
    """docs/research-discovery-plan.md §3: fail-open applies per-instance —
    an angle's gather stage not writing its finding file must not cancel
    the other angles or the run; a fixed later stage (synthesize) still
    runs regardless, since the dynamic block itself is never critical."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspaces" / "daily"
    workspace_root.mkdir(parents=True)
    (workspace_root / "results").mkdir()
    _write_plan_file(
        workspace_root,
        "research_plan_pli-semis_2026-08-30.json",
        [{"id": "policy", "question": "q1"}, {"id": "names", "question": "q2"}],
    )

    stages = [_dynamic_stage(), _stage("synthesize", critical=True, produces=["{workspace}/results/x.md"])]
    sessions = [_FakeSession(["policy"]), _FakeSession(["names"]), _FakeSession(["synth"])]
    harness = _FakeHarness(sessions)

    # Neither gather instance's fake session actually writes a finding
    # file, so both come back "expected output missing" — fail-open, not
    # critical. synthesize's own fake session does write its produces
    # file, standing in for a real session's tool call.
    orig_synth_send = sessions[2].send

    async def _synth_send_and_write(prompt, *, workspace_root=None):
        (workspace_root / "results" / "x.md").write_text("done")
        async for chunk in orig_synth_send(prompt, workspace_root=workspace_root):
            yield chunk

    sessions[2].send = _synth_send_and_write

    final_text, _ = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, "body", stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )

    assert len(harness.opened_tools) == 3  # both gather instances + synthesize, none skipped
    assert final_text == "synth"


def test_research_discovery_gather_real_skill_runs_end_to_end(tmp_path, monkeypatch):
    """Integration check against the real .claude/skills/research-discovery-
    gather/SKILL.md (docs/research-discovery-plan.md §3), not a synthetic
    stage list — proves the actual authored frontmatter (a dynamic gather
    stage + a critical synthesize stage) drives through run_staged_skill
    correctly: one fresh session per angle, then synthesize, with the
    engine's Sources footer + SEBI disclaimer appended to the returned
    text, and no separate results/ file (expected_outputs: [] — the real
    durable output is the research/ bucket file synthesize itself writes)."""
    import engine.skills as skills_module

    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "results").mkdir()
    _write_plan_file(
        workspace_root,
        "research_plan_pli-semis_2026-08-30.json",
        [
            {"id": "policy", "question": "What did the tranche fund?", "tool_hint": "india_news.get_news"},
            {"id": "names", "question": "Which listed names are exposed?"},
        ],
    )

    # SKILLS_ROOT is left unpatched — this reads the real, committed SKILL.md.
    stages = skills_module.load_stages("research-discovery-gather")
    skill_body = skills_module.load_skill_body("research-discovery-gather")

    sessions = [
        _FakeSession(
            ["policy finding"], captures=[("india_news", "get_news", workspace_root / "data" / "news.json")]
        ),
        _FakeSession(["names finding"]),
        _FakeSession(["# Brief"]),
    ]
    orig_synth_send = sessions[2].send

    async def _synth_send(prompt, *, workspace_root=None):
        (workspace_root / "research" / "themes").mkdir(parents=True, exist_ok=True)
        (workspace_root / "research" / "themes" / "pli-semiconductors.md").write_text("# PLI semis")
        async for chunk in orig_synth_send(prompt, workspace_root=workspace_root):
            yield chunk

    sessions[2].send = _synth_send
    harness = _FakeHarness(sessions)

    final_text, all_captures = asyncio.run(
        staged_skills.run_staged_skill(
            harness, FAKE_TOOLS, skill_body, stages, workspace_root=workspace_root, date="2026-08-30"
        )
    )
    full_text = staged_skills.compose_and_save(
        final_text, all_captures, skill_name="research-discovery-gather", workspace_root=workspace_root
    )

    assert len(harness.opened_tools) == 3  # 2 gather instances + synthesize, none skipped
    assert full_text.startswith("# Brief")
    assert "SEBI-registered" in full_text  # engine-appended disclaimer present
    assert list((workspace_root / "results").iterdir()) == []  # no engine-composed file — expected_outputs: []
    assert (workspace_root / "research" / "themes" / "pli-semiconductors.md").read_text() == "# PLI semis"


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


    from engine.time_ist import today_ist

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


def test_compose_and_save_strips_narration_before_the_final_content_marker(tmp_path, monkeypatch, capsys):
    """Regression test for issue #66: a Glob false-negative's recovery
    narration leaked verbatim into a saved digest file. The compose
    stage's own text can include the marker to mark where the real
    deliverable starts; anything before it must be discarded, not saved."""
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

    from engine.time_ist import today_ist

    final_text = (
        "The files exist — my earlier glob just used the wrong relative "
        "path. Let me read the index quote and FII/DII data.\n\n"
        "<!-- minty:compose-final -->\n"
        "# Morning Digest\nAll good."
    )
    full_text = staged_skills.compose_and_save(
        final_text,
        [("india_price", "get_quote", workspace_root / "data" / "live_quotes.json")],
        skill_name="morning-digest",
        workspace_root=workspace_root,
    )

    assert full_text.startswith("# Morning Digest\nAll good.")
    assert "glob just used the wrong relative path" not in full_text
    saved = workspace_root / "results" / f"digest_{today_ist()}.md"
    assert "glob just used the wrong relative path" not in saved.read_text()
    assert "[compose]" not in capsys.readouterr().out


def test_compose_and_save_falls_back_to_full_text_with_a_diagnostic_when_marker_missing(
    tmp_path, monkeypatch, capsys
):
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

    full_text = staged_skills.compose_and_save(
        "# Digest\nAll good.",
        [("india_price", "get_quote", workspace_root / "data" / "live_quotes.json")],
        skill_name="morning-digest",
        workspace_root=workspace_root,
    )

    assert full_text.startswith("# Digest\nAll good.")
    assert "didn't emit the" in capsys.readouterr().out


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
