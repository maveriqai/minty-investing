"""Tests for the new multi-turn pieces: `ClaudeSession` (wraps a connected
client, holds conversation state across `send()` calls) and
`engine/interactive.py`'s per-turn print/error logic.

Uses fake stand-ins for the SDK's own message types rather than the real
`claude_agent_sdk` classes — `ClaudeSession.send()` dispatches on
`type(message).__name__`, not `isinstance`, specifically so it doesn't need
to import the real types to be tested. Whether conversation state actually
persists across turns in the real `ClaudeSDKClient` is a live-verification
question, not a unit-test one — see the manual smoke test this build was
verified against.
"""

import asyncio

import engine.interactive as interactive_module
from engine.harnesses.base import EngineResult
from engine.harnesses.claude_agent_sdk import ClaudeSession, _wait_for_mcp_servers_ready
from engine.interactive import _run_turn


class TextBlock:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class ResultMessage:
    def __init__(self, subtype, result=None):
        self.subtype = subtype
        self.result = result


class _FakeClient:
    """Stands in for `ClaudeSDKClient` — records queries, replays a fixed
    message sequence per prompt."""

    def __init__(self, messages_by_prompt):
        self._messages_by_prompt = messages_by_prompt
        self.queried: list[str] = []

    async def query(self, prompt: str) -> None:
        self.queried.append(prompt)

    async def receive_response(self):
        for message in self._messages_by_prompt[self.queried[-1]]:
            yield message


async def _collect(session: ClaudeSession, prompt: str) -> list[str]:
    return [chunk async for chunk in session.send(prompt)]


def test_claude_session_yields_text_blocks_in_order_and_records_success():
    client = _FakeClient(
        {
            "hello": [
                AssistantMessage(content=[TextBlock("Hi "), TextBlock("there")]),
                ResultMessage(subtype="success", result="Hi there"),
            ]
        }
    )
    session = ClaudeSession(client)

    chunks = asyncio.run(_collect(session, "hello"))

    assert chunks == ["Hi ", "there"]
    assert session.last_result == EngineResult(ok=True, text="Hi there", error_kind=None, raw=session.last_result.raw)


def test_claude_session_records_failure_result_and_yields_no_text():
    client = _FakeClient({"bad": [ResultMessage(subtype="error_during_execution")]})
    session = ClaudeSession(client)

    chunks = asyncio.run(_collect(session, "bad"))

    assert chunks == []
    assert not session.last_result.ok
    assert session.last_result.error_kind == "error_during_execution"


def test_claude_session_send_is_called_per_turn_on_the_same_client():
    # Proves send() re-queries the same underlying client rather than
    # reconnecting — the actual conversation-history persistence is the
    # client's own job (ClaudeSDKClient), verified live, not here.
    client = _FakeClient(
        {
            "first": [ResultMessage(subtype="success", result="one")],
            "second": [ResultMessage(subtype="success", result="two")],
        }
    )
    session = ClaudeSession(client)

    asyncio.run(_collect(session, "first"))
    assert session.last_result.text == "one"
    asyncio.run(_collect(session, "second"))
    assert session.last_result.text == "two"
    assert client.queried == ["first", "second"]


class _FakeStatusClient:
    """Stands in for ClaudeSDKClient.get_mcp_status() — reports 'pending'
    for a fixed number of polls, then 'connected'."""

    def __init__(self, pending_polls: int, server_names: list[str]):
        self._pending_polls = pending_polls
        self._server_names = server_names
        self.calls = 0

    async def get_mcp_status(self):
        self.calls += 1
        status = "pending" if self.calls <= self._pending_polls else "connected"
        return {"mcpServers": [{"name": name, "status": status} for name in self._server_names]}


def test_wait_for_mcp_servers_ready_returns_once_all_connected():
    client = _FakeStatusClient(pending_polls=2, server_names=["india_price", "kite_gateway"])
    asyncio.run(
        _wait_for_mcp_servers_ready(
            client, {"india_price", "kite_gateway"}, timeout_s=5.0, poll_interval_s=0.01
        )
    )
    assert client.calls == 3  # 2 pending polls, then the 3rd sees all connected


def test_wait_for_mcp_servers_ready_returns_immediately_when_expected_is_empty():
    client = _FakeStatusClient(pending_polls=100, server_names=[])
    asyncio.run(_wait_for_mcp_servers_ready(client, set(), timeout_s=5.0, poll_interval_s=0.01))
    assert client.calls == 0


def test_wait_for_mcp_servers_ready_gives_up_at_timeout_without_hanging():
    client = _FakeStatusClient(pending_polls=10_000, server_names=["india_price"])
    # Never connects — must still return (not hang) once timeout_s elapses.
    asyncio.run(
        _wait_for_mcp_servers_ready(client, {"india_price"}, timeout_s=0.05, poll_interval_s=0.01)
    )
    assert client.calls > 0


class _FakeSession:
    def __init__(self, chunks, result, last_over_budget=None):
        self._chunks = chunks
        self.last_result = result
        self.last_over_budget = last_over_budget or []
        self.received_prompts: list[str] = []

    async def send(self, prompt: str, *, workspace_root=None):
        self.received_prompts.append(prompt)
        for chunk in self._chunks:
            yield chunk


def _isolate_watch_roots(tmp_path, monkeypatch):
    """`_run_turn` always snapshots FIXED_WATCH_ROOTS — point it at a fake
    repo layout under tmp_path instead of the real one, so these tests
    don't depend on (or get confused by) this repo's actual data/results/
    workspaces contents."""
    data_dir = tmp_path / "data"
    results_dir = tmp_path / "results"
    workspaces_dir = tmp_path / "workspaces"
    for d in (data_dir, results_dir, workspaces_dir):
        d.mkdir()
    monkeypatch.setattr(interactive_module, "FIXED_WATCH_ROOTS", [data_dir, results_dir, workspaces_dir])
    return workspaces_dir


def test_run_turn_prints_streamed_chunks_with_trailing_newline(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    session = _FakeSession(
        ["Hello", " world"], EngineResult(ok=True, text="Hello world", error_kind=None, raw=None)
    )
    asyncio.run(_run_turn(session, "hi"))
    assert "Hello world" in capsys.readouterr().out


def test_run_turn_prints_over_budget_lines_as_a_diagnostic(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    session = _FakeSession(
        ["ok"],
        EngineResult(ok=True, text="ok", error_kind=None, raw=None),
        last_over_budget=["india_news.get_news called 33 times this turn (skill declares an expected ceiling of 25)"],
    )
    asyncio.run(_run_turn(session, "hi"))
    out = capsys.readouterr().out
    assert "[budget] india_news.get_news called 33 times this turn" in out


def test_run_turn_reports_error_kind_to_stderr_on_failed_turn(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    session = _FakeSession([], EngineResult(ok=False, text=None, error_kind="session_limit", raw=None))
    asyncio.run(_run_turn(session, "hi"))
    assert "session_limit" in capsys.readouterr().err


def test_run_turn_without_workspace_sends_prompt_unmodified(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))
    asyncio.run(_run_turn(session, "hi"))
    assert session.received_prompts == ["hi"]


def test_run_turn_with_workspace_injects_exact_path_into_the_prompt(tmp_path, monkeypatch, capsys):
    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "test-scan"
    (workspace_root / "data").mkdir(parents=True)
    (workspace_root / "results").mkdir(parents=True)
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    asyncio.run(_run_turn(session, "scan RELIANCE", workspace_root=workspace_root))

    assert len(session.received_prompts) == 1
    sent = session.received_prompts[0]
    assert str(workspace_root) in sent
    assert "scan RELIANCE" in sent
    assert "not something to create yourself" in sent


def test_run_turn_appends_the_turn_to_the_transcript_when_given_a_path(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    transcript_path = tmp_path / "workspace" / "sessions" / "2026-08-25T09-00-00.md"
    session = _FakeSession(["Hello", " world"], EngineResult(ok=True, text="Hello world", error_kind=None, raw=None))

    asyncio.run(_run_turn(session, "hi", transcript_path=transcript_path))

    text = transcript_path.read_text()
    assert "hi" in text
    assert "Hello world" in text


def test_run_turn_marks_a_failed_turn_in_the_transcript_instead_of_recording_it_as_success(
    tmp_path, monkeypatch, capsys
):
    # A failed turn yields no text (see test_claude_session_records_failure_result_and_yields_no_text),
    # so without an explicit marker the transcript would show a blank "##
    # minty" block indistinguishable from a real, if terse, answer (issue
    # #13 review).
    _isolate_watch_roots(tmp_path, monkeypatch)
    transcript_path = tmp_path / "workspace" / "sessions" / "2026-08-25T09-00-00.md"
    session = _FakeSession([], EngineResult(ok=False, text=None, error_kind="session_limit", raw=None))

    asyncio.run(_run_turn(session, "hi", transcript_path=transcript_path))

    text = transcript_path.read_text()
    assert "turn ended without success: session_limit" in text


def test_run_turn_does_not_crash_when_the_transcript_write_fails(tmp_path, monkeypatch, capsys):
    # An audit-only side effect failing (disk full, permissions) must not
    # take the primary REPL down with it (issue #13 review). Simulated by
    # pointing transcript_path at a location whose parent can never be
    # created — a file standing where a directory needs to go.
    _isolate_watch_roots(tmp_path, monkeypatch)
    blocking_file = tmp_path / "workspace" / "sessions"
    blocking_file.parent.mkdir(parents=True)
    blocking_file.write_text("not a directory")
    transcript_path = blocking_file / "2026-08-25T09-00-00.md"
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    asyncio.run(_run_turn(session, "hi", transcript_path=transcript_path))

    assert "[transcript] couldn't write to" in capsys.readouterr().err


def test_run_turn_does_not_write_a_transcript_when_no_path_given(tmp_path, monkeypatch, capsys):
    _isolate_watch_roots(tmp_path, monkeypatch)
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    asyncio.run(_run_turn(session, "hi"))

    assert not (tmp_path / "workspace" / "sessions").exists()


def test_run_turn_reports_no_files_changed_when_nothing_changed(tmp_path, monkeypatch, capsys):
    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "test-scan"
    (workspace_root / "results").mkdir(parents=True)
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    asyncio.run(_run_turn(session, "scan RELIANCE", workspace_root=workspace_root))

    assert "[no files changed this turn]" in capsys.readouterr().out


def test_run_turn_reports_files_that_changed_but_match_no_known_skill(tmp_path, monkeypatch, capsys):
    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "test-scan"
    (workspace_root / "results").mkdir(parents=True)
    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    async def _send_and_write(prompt, *, workspace_root=None):
        (workspace_root / "results" / "written_during_turn.md").write_text("evidence")
        for chunk in ["ok"]:
            yield chunk

    session.send = _send_and_write
    # skill_names=[] (or a skill declaring nothing) -> nothing to match against,
    # so the change is reported but unclassified.
    asyncio.run(_run_turn(session, "scan RELIANCE", workspace_root=workspace_root, skill_names=[]))

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" in out
    assert "written_during_turn.md" in out


def test_run_turn_reports_a_match_against_a_skills_declared_pattern(tmp_path, monkeypatch, capsys):
    import engine.skills as skills_module

    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "test-scan"
    (workspace_root / "results").mkdir(parents=True)

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "red-flag-scan"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: red-flag-scan\ndescription: test\n'
        'expected_outputs:\n  - "workspaces/{workspace}/results/red_flags_*_{date}.json"\n---\n'
    )
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", skills_root)

    session = _FakeSession(["ok"], EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    async def _send_and_write(prompt, *, workspace_root=None):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        (workspace_root / "results" / f"red_flags_RELIANCE_{today}.json").write_text("{}")
        for chunk in ["ok"]:
            yield chunk

    session.send = _send_and_write
    asyncio.run(
        _run_turn(session, "scan RELIANCE", workspace_root=workspace_root, skill_names=["red-flag-scan"])
    )

    out = capsys.readouterr().out
    assert "matches red-flag-scan's expected output" in out
    assert "red_flags_RELIANCE_" in out


def _write_digest_skill(tmp_path, monkeypatch):
    import engine.skills as skills_module

    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "morning-digest"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: morning-digest\ndescription: test\n'
        'expected_outputs:\n'
        '  - "workspaces/{workspace}/results/digest_{date}.json"\n'
        '  - "workspaces/{workspace}/results/digest_{date}.md"\n---\n'
    )
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", skills_root)


def test_run_turn_saves_composed_text_to_a_skills_declared_md_output(tmp_path, monkeypatch, capsys):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "daily"
    (workspace_root / "results").mkdir(parents=True)
    _write_digest_skill(tmp_path, monkeypatch)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

    session = _FakeSession(["ignored"], EngineResult(ok=True, text="ignored", error_kind=None, raw=None))

    async def _send_and_write(prompt, *, workspace_root=None):
        (workspace_root / "results" / f"digest_{today}.json").write_text("{}")
        for chunk in ["# Morning Digest\n", "Portfolio is up.\n"]:
            yield chunk

    session.send = _send_and_write
    asyncio.run(
        _run_turn(session, "give me the digest", workspace_root=workspace_root, skill_names=["morning-digest"])
    )

    md_path = workspace_root / "results" / f"digest_{today}.md"
    assert md_path.read_text() == "# Morning Digest\nPortfolio is up.\n"
    out = capsys.readouterr().out
    assert f"[engine saved morning-digest's composed output — {md_path}]" in out
    assert "matches morning-digest's expected output" in out


def test_run_turn_does_not_save_md_output_when_json_output_did_not_change(tmp_path, monkeypatch, capsys):
    workspaces_dir = _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = workspaces_dir / "daily"
    (workspace_root / "results").mkdir(parents=True)
    _write_digest_skill(tmp_path, monkeypatch)

    session = _FakeSession(["just chatting"], EngineResult(ok=True, text="just chatting", error_kind=None, raw=None))
    asyncio.run(
        _run_turn(session, "hi", workspace_root=workspace_root, skill_names=["morning-digest"])
    )

    assert list((workspace_root / "results").iterdir()) == []
    assert "[engine saved" not in capsys.readouterr().out


class _FakeHarness:
    """Stands in for `Harness` — `open_session` yields the given
    `_FakeSession` directly, no real client/connection involved."""

    def __init__(self, session):
        self._session = session

    def open_session(self, tools):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


def test_repl_surfaces_pending_memory_candidates_as_the_first_turn(tmp_path, monkeypatch):
    from engine.interactive import _repl
    from engine.memory_candidates import append_candidate, candidates_path

    _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = tmp_path / "workspace"
    (workspace_root / "data").mkdir(parents=True)
    (workspace_root / "results").mkdir(parents=True)
    append_candidate(candidates_path(workspace_root), "User seems done with PSU banks.", "from prior session")

    session = _FakeSession(["noted"], EngineResult(ok=True, text="noted", error_kind=None, raw=None))
    harness = _FakeHarness(session)
    # No follow-up turn — the REPL loop's own input() call hits EOF right
    # after the synthesized review turn, ending the session.
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))

    asyncio.run(_repl(harness, workspace_root))

    assert len(session.received_prompts) == 1
    sent = session.received_prompts[0]
    assert "User seems done with PSU banks." in sent
    assert "haven't been reviewed yet" in sent
    # Cleared as soon as it's handed to the turn — see
    # engine/memory_candidates.py's docstring for why.
    assert candidates_path(workspace_root).read_text() == ""


def test_repl_skips_the_review_turn_when_nothing_is_staged(tmp_path, monkeypatch):
    from engine.interactive import _repl

    _isolate_watch_roots(tmp_path, monkeypatch)
    workspace_root = tmp_path / "workspace"
    (workspace_root / "data").mkdir(parents=True)
    (workspace_root / "results").mkdir(parents=True)

    session = _FakeSession([], EngineResult(ok=True, text="", error_kind=None, raw=None))
    harness = _FakeHarness(session)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))

    asyncio.run(_repl(harness, workspace_root))

    assert session.received_prompts == []
