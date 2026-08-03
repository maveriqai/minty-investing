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
    def __init__(self, chunks, result):
        self._chunks = chunks
        self.last_result = result

    async def send(self, prompt: str):
        for chunk in self._chunks:
            yield chunk


def test_run_turn_prints_streamed_chunks_with_trailing_newline(capsys):
    session = _FakeSession(
        ["Hello", " world"], EngineResult(ok=True, text="Hello world", error_kind=None, raw=None)
    )
    asyncio.run(_run_turn(session, "hi"))
    assert capsys.readouterr().out == "Hello world\n"


def test_run_turn_reports_error_kind_to_stderr_on_failed_turn(capsys):
    session = _FakeSession([], EngineResult(ok=False, text=None, error_kind="session_limit", raw=None))
    asyncio.run(_run_turn(session, "hi"))
    assert "session_limit" in capsys.readouterr().err
