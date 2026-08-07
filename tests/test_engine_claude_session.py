"""Tests ClaudeSession.send()'s auto-capture wiring against a fake
ClaudeSDKClient — proves the (ToolUseBlock -> ToolResultBlock) pairing and
the workspace_root on/off switch, without a real SDK connection. Message
classes below are named to match claude_agent_sdk.types exactly, since
ClaudeSession dispatches on type(x).__name__, not isinstance.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.harnesses.claude_agent_sdk import ClaudeSession
from engine.tool_budget import TurnBudgetTracker

_TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


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
    content: list = field(default_factory=list)


@dataclass
class UserMessage:
    content: list = field(default_factory=list)


@dataclass
class ResultMessage:
    subtype: str
    result: str | None = None


class _FakeClient:
    def __init__(self, messages):
        self._messages = messages
        self.queried_prompt = None

    async def query(self, prompt):
        self.queried_prompt = prompt

    async def receive_response(self):
        for message in self._messages:
            yield message


def _drain(session, prompt, **kwargs):
    async def _run():
        return [chunk async for chunk in session.send(prompt, **kwargs)]

    return asyncio.run(_run())


def test_send_captures_matching_tool_result_to_workspace_data(tmp_path):
    messages = [
        AssistantMessage(content=[
            TextBlock(text="checking surveillance..."),
            ToolUseBlock(id="t1", name="mcp__india_filings__get_surveillance_list", input={"list_type": "ASM"}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content='{"source": "x", "data": []}')]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "scan for surveillance flags", workspace_root=tmp_path)

    assert chunks[0] == "checking surveillance..."
    captured = tmp_path / "data" / f"surveillance_asm_{_TODAY}.json"
    assert captured.read_text() == '{"source": "x", "data": []}'
    assert session.last_result.ok is True


def test_send_appends_sources_footer_when_workspace_root_set_and_something_captured(tmp_path):
    messages = [
        AssistantMessage(content=[
            TextBlock(text="checking surveillance..."),
            ToolUseBlock(id="t1", name="mcp__india_filings__get_surveillance_list", input={"list_type": "ASM"}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content='{"source": "x", "data": []}')]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "scan for surveillance flags", workspace_root=tmp_path)

    footer = chunks[-1]
    assert "**Sources**" in footer
    assert "india_filings.get_surveillance_list" in footer
    assert "SEBI-registered investment adviser" in footer
    assert session.last_captures == [
        ("india_filings", "get_surveillance_list", tmp_path / "data" / f"surveillance_asm_{_TODAY}.json")
    ]


def test_send_appends_no_footer_when_nothing_captured(tmp_path):
    messages = [
        AssistantMessage(content=[TextBlock(text="just chatting")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "hi", workspace_root=tmp_path)

    assert chunks == ["just chatting"]
    assert session.last_captures == []


def test_send_appends_no_footer_when_workspace_root_is_none():
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__kite_gateway__get_holdings", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="[]")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "fetch holdings")

    assert chunks == []
    assert session.last_captures == []


def test_send_handles_list_shaped_tool_result_content(tmp_path):
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__kite_gateway__get_holdings", input={}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": '{"data": []}'}])
        ]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "fetch holdings", workspace_root=tmp_path)

    captured = tmp_path / "data" / f"holdings_{_TODAY}.json"
    assert captured.read_text() == '{"data": []}'


def test_send_skips_capture_when_workspace_root_is_none(tmp_path):
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__kite_gateway__get_holdings", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="[]")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "fetch holdings")

    assert not (tmp_path / "data").exists()


def test_send_skips_capture_for_error_results(tmp_path):
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__kite_gateway__get_holdings", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="boom", is_error=True)]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "fetch holdings", workspace_root=tmp_path)

    assert not (tmp_path / "data" / f"holdings_{_TODAY}.json").exists()


def test_send_ignores_tool_results_with_no_matching_pending_call(tmp_path):
    messages = [
        UserMessage(content=[ToolResultBlock(tool_use_id="orphan", content="[]")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "anything", workspace_root=tmp_path)

    assert not (tmp_path / "data").exists()


def test_send_resets_the_budget_tracker_at_the_start_of_each_turn():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 1})
    tracker.record("mcp__india_news__get_news")
    tracker.record("mcp__india_news__get_news")
    assert tracker.over_budget() != []  # already over budget from a prior turn

    messages = [ResultMessage(subtype="success", result="done")]
    session = ClaudeSession(_FakeClient(messages), tracker)

    _drain(session, "next turn")

    assert session.last_over_budget == []  # reset at the start of this turn, nothing called since


def test_send_records_budgeted_tool_calls_and_reports_when_over_budget():
    tracker = TurnBudgetTracker({("india_news", "get_news"): 1})
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__india_news__get_news", input={"query": "RELIANCE"}),
            ToolUseBlock(id="t2", name="mcp__india_news__get_news", input={"query": "RELIANCE INDUSTRIES"}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content='{"data": []}'),
            ToolResultBlock(tool_use_id="t2", content='{"data": []}'),
        ]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages), tracker)

    _drain(session, "check news")

    assert len(session.last_over_budget) == 1
    assert "india_news.get_news" in session.last_over_budget[0]
    assert "2 times" in session.last_over_budget[0]


def test_send_ignores_non_mcp_tool_calls(tmp_path):
    messages = [
        AssistantMessage(content=[ToolUseBlock(id="t1", name="Write", input={"file_path": "x", "content": "y"})]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "write a file", workspace_root=tmp_path)

    assert not (tmp_path / "data").exists()
