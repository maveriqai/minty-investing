"""Tests ClaudeSession.send()'s auto-capture wiring against a fake
ClaudeSDKClient — proves the (ToolUseBlock -> ToolResultBlock) pairing and
the workspace_root on/off switch, without a real SDK connection. Message
classes below are named to match claude_agent_sdk.types exactly, since
ClaudeSession dispatches on type(x).__name__, not isinstance.
"""

import asyncio
from dataclasses import dataclass, field

from engine.harnesses.claude_agent_sdk import ClaudeSession
from engine.time_ist import today_ist
from engine.tool_budget import TurnBudgetTracker

_TODAY = today_ist()


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
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content='{"source": "x", "as_of": "2026-08-18", "data": []}')]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "scan for surveillance flags", workspace_root=tmp_path)

    assert chunks[0] == "checking surveillance..."
    captured = tmp_path / "data" / f"surveillance_asm_{_TODAY}.json"
    assert captured.read_text() == '{"source": "x", "as_of": "2026-08-18", "data": []}'
    assert session.last_result.ok is True


def test_send_appends_sources_footer_when_workspace_root_set_and_something_captured(tmp_path):
    messages = [
        AssistantMessage(content=[
            TextBlock(text="checking surveillance..."),
            ToolUseBlock(id="t1", name="mcp__india_filings__get_surveillance_list", input={"list_type": "ASM"}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content='{"source": "x", "as_of": "2026-08-18", "data": []}')
        ]),
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


def test_send_force_disclaimer_appends_bare_disclaimer_when_nothing_captured(tmp_path):
    """Issue #65: the memory-candidate review turn discusses findings
    already grounded in an earlier turn/session, so it makes no fresh
    captures itself — the normal captures-based footer never fires, but
    force_disclaimer should still get the SEBI disclaimer attached, with
    no Sources list (there's nothing new to itemize)."""
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[TextBlock(text="Here's what's staged for review.")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "review staged candidates", workspace_root=tmp_path, force_disclaimer=True)

    full_text = "".join(chunks)
    assert DISCLAIMER in full_text
    assert "**Sources**" not in full_text


def test_send_force_disclaimer_is_a_noop_when_disclaimer_already_present(tmp_path):
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[TextBlock(text=f"Here's what's staged.\n\n---\n{DISCLAIMER}\n")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "review staged candidates", workspace_root=tmp_path, force_disclaimer=True)

    full_text = "".join(chunks)
    assert full_text.count(DISCLAIMER) == 1


def test_send_force_disclaimer_does_not_duplicate_a_real_footer(tmp_path):
    """When this turn did capture something, the normal Sources-footer
    branch already appends the disclaimer as part of it — force_disclaimer
    must not additionally append the bare disclaimer on top."""
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[
            TextBlock(text="checking surveillance..."),
            ToolUseBlock(id="t1", name="mcp__india_filings__get_surveillance_list", input={"list_type": "ASM"}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content='{"source": "x", "as_of": "2026-08-18", "data": []}')
        ]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "scan for surveillance flags", workspace_root=tmp_path, force_disclaimer=True)

    full_text = "".join(chunks)
    assert full_text.count(DISCLAIMER) == 1
    assert full_text.count("**Sources**") == 1


def test_send_appends_bare_disclaimer_when_a_tool_call_isnt_capture_worthy(tmp_path):
    """Issue #70 (found live re-verifying the earlier fix): `captures`
    only ever reflects raw Layer-2 MCP results — a turn built entirely
    from Minty's own internal tools (fetch_holdings, run_health_check,
    check_identity_match) never trips the normal captures-based branch,
    regardless of how much real portfolio data it touched. A real "what
    are my holdings" reply shipped with zero disclaimer at all this way.
    Any tool call at all (not just a capture-worthy one) should now be
    enough to force the bare disclaimer, without force_disclaimer set."""
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[
            TextBlock(text="Here's your holdings."),
            ToolUseBlock(id="t1", name="mcp__fetch_holdings__fetch_holdings", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="wrote holdings_2026-09-03.json — 96 holdings")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "what are my holdings", workspace_root=tmp_path)

    full_text = "".join(chunks)
    assert DISCLAIMER in full_text
    assert "**Sources**" not in full_text
    assert session.last_captures == []


def test_send_appends_no_disclaimer_when_nothing_happened_this_turn(tmp_path):
    """Guards against over-triggering: a plain chit-chat turn with zero
    tool calls and no force_disclaimer must stay exactly as before —
    build_footer's own "nothing to cite" reasoning still holds when
    nothing was actually done this turn."""
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[TextBlock(text="Hi there!")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "hi", workspace_root=tmp_path)

    full_text = "".join(chunks)
    assert DISCLAIMER not in full_text


def test_send_appends_no_disclaimer_for_tool_calls_when_workspace_root_unset(tmp_path):
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[
            TextBlock(text="checking..."),
            ToolUseBlock(id="t1", name="mcp__fetch_holdings__fetch_holdings", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="wrote holdings_2026-09-03.json — 96 holdings")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "what are my holdings")

    full_text = "".join(chunks)
    assert DISCLAIMER not in full_text


def test_send_skips_footer_when_model_already_wrote_the_disclaimer(tmp_path):
    """Every skill's SKILL.md says not to compose its own closing footer —
    but that's a prose instruction the model doesn't reliably follow
    (issue #27, live-verified: a real thesis-tracker run still wrote its
    own disclaimer despite the updated wording). Appending the engine's own
    footer on top would just create the exact visible duplicate #27 is
    about, so a self-authored disclaimer must suppress the engine's own,
    not stack with it."""
    from engine.sources_footer import DISCLAIMER

    messages = [
        AssistantMessage(content=[
            TextBlock(text=f"Thesis saved.\n\n---\n{DISCLAIMER}\n\n**Sources:** india_price.get_quote"),
            ToolUseBlock(id="t1", name="mcp__india_price__get_quote", input={}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content='{"source": "x", "as_of": "2026-08-18", "data": []}')
        ]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "track a thesis", workspace_root=tmp_path)

    full_text = "".join(chunks)
    assert full_text.count(DISCLAIMER) == 1
    assert full_text.count("**Sources") == 1


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
            ToolResultBlock(
                tool_use_id="t1",
                content=[{"type": "text", "text": '{"source": "kite", "as_of": "2026-08-18", "data": []}'}],
            )
        ]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "fetch holdings", workspace_root=tmp_path)

    captured = tmp_path / "data" / f"holdings_{_TODAY}.json"
    assert captured.read_text() == '{"source": "kite", "as_of": "2026-08-18", "data": []}'


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


def test_send_separates_consecutive_text_chunks_with_a_blank_line():
    """A turn's narration commonly spans several separate TextBlocks
    interleaved with tool calls (e.g. "Anchor exists." ... tool call ...
    "Identity matches."). Concatenating them with no separator glues them
    together mid-sentence live in the terminal and in the saved transcript
    (issue #28) — each chunk after the first must start on its own line."""
    messages = [
        AssistantMessage(content=[TextBlock(text="Anchor exists.")]),
        AssistantMessage(content=[TextBlock(text="Identity matches.")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "check identity")

    assert chunks == ["Anchor exists.", "\n\nIdentity matches."]
    assert "".join(chunks) == "Anchor exists.\n\nIdentity matches."


def test_send_yields_staged_tool_result_verbatim_and_suppresses_later_model_text(tmp_path):
    """A run_staged_<skill> call's own returned text already is the finished,
    fully-composed result (built by engine/staged_skills.py's
    compose_and_save from every stage's own tool calls, none of which this
    session ever saw). The model's own subsequent paraphrase — and this
    session's own captures-based footer, which would only ever cite
    whatever this outer turn itself called directly — must not appear
    (issue #15)."""
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__staged_workflows__run_staged_morning_digest", input={}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t1", content="Digest body\n\n---\n**Sources**\n- everything cited\n")
        ]),
        AssistantMessage(content=[TextBlock(text="Here's your digest, missing the real footer")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "give me the morning digest", workspace_root=tmp_path)

    assert chunks == ["Digest body\n\n---\n**Sources**\n- everything cited\n"]


def test_send_skips_its_own_footer_when_a_staged_tool_was_called(tmp_path):
    """Even if this outer turn also made a real, capturable call of its own
    before the staged call, the session's own footer must not fire once a
    staged result is present — it would only cite that one call, not the
    full multi-stage picture the staged tool's own text already carries."""
    messages = [
        AssistantMessage(content=[
            ToolUseBlock(id="t0", name="mcp__kite_gateway__get_holdings", input={}),
        ]),
        UserMessage(content=[
            ToolResultBlock(tool_use_id="t0", content='{"source": "kite", "as_of": "2026-08-18", "data": []}')
        ]),
        AssistantMessage(content=[
            ToolUseBlock(id="t1", name="mcp__staged_workflows__run_staged_morning_digest", input={}),
        ]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="Digest body with its own footer")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    chunks = _drain(session, "give me the morning digest", workspace_root=tmp_path)

    assert chunks == ["Digest body with its own footer"]
    assert "**Sources**" not in "".join(chunks)
    assert session.last_captures == [
        ("kite_gateway", "get_holdings", tmp_path / "data" / f"holdings_{_TODAY}.json")
    ]


def test_send_ignores_non_mcp_tool_calls(tmp_path):
    messages = [
        AssistantMessage(content=[ToolUseBlock(id="t1", name="Write", input={"file_path": "x", "content": "y"})]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok")]),
        ResultMessage(subtype="success", result="done"),
    ]
    session = ClaudeSession(_FakeClient(messages))

    _drain(session, "write a file", workspace_root=tmp_path)

    assert not (tmp_path / "data").exists()
