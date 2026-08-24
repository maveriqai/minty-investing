"""Tests for engine/guardrail.py's tool-name suffix helper, shared by
GuardrailPolicy.is_denied and the identity-check hooks in
engine/harnesses/claude_agent_sdk.py (consolidated during issue #19's
review to avoid two hand-maintained copies of the same rsplit logic).
"""

from engine.guardrail import GuardrailPolicy, tool_name_suffix


def test_tool_name_suffix_extracts_the_part_after_the_last_separator():
    assert tool_name_suffix("mcp__kite_gateway__get_holdings") == "get_holdings"


def test_tool_name_suffix_is_none_for_an_unnamespaced_tool():
    assert tool_name_suffix("Bash") is None
    assert tool_name_suffix("Read") is None


def test_guardrail_policy_denies_order_tools_under_any_server():
    policy = GuardrailPolicy()
    assert policy.is_denied("mcp__kite_gateway__place_order") is True
    assert policy.is_denied("mcp__kite__place_order") is True
    assert policy.is_denied("mcp__kite_gateway__get_holdings") is False
    assert policy.is_denied("Bash") is False
