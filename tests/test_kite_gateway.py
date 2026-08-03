"""Smoke tests for the kite_gateway MCP server.

Offline only: the actual connect to mcp.kite.trade needs a real network
call and isn't covered here — see server.py's module docstring for what
was verified live instead. These tests cover the structural guarantees
that don't need a live upstream: the allow/deny tool split, envelope
shape, that call_tool rejects a denied tool before ever touching the
network, and that concurrent first calls can't race into two different
Kite sessions (the bug caught live 2026-07-24 — see _Upstream's docstring
in server.py).

`server` is loaded via importlib under a unique module name, same fix as
test_india_filings.py — every mcp/<name>/ dir has its own server.py.
"""

import asyncio
import importlib.util
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import anyio
import mcp.types as types
import pytest

MCP_DIR = Path(__file__).parent.parent / "mcp"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = _load("kite_gateway_server", MCP_DIR / "kite_gateway" / "server.py")


def _tool(name: str) -> types.Tool:
    return types.Tool(name=name, inputSchema={"type": "object", "properties": {}})


def test_allowed_and_denied_tools_are_disjoint():
    assert server.ALLOWED_TOOLS.isdisjoint(server.DENIED_TOOLS)
    assert len(server.ALLOWED_TOOLS) == 16
    assert len(server.DENIED_TOOLS) == 6


def test_filter_upstream_tools_keeps_only_allowed():
    upstream_tools = [_tool("get_holdings"), _tool("place_order"), _tool("some_future_tool")]
    kept = server.filter_upstream_tools(upstream_tools)
    assert [t.name for t in kept] == ["get_holdings"]


def test_filter_upstream_tools_drops_denied_even_if_hypothetically_allowed(monkeypatch):
    # Defense in depth: even if ALLOWED_TOOLS were ever edited to accidentally
    # include a denied name, filter_upstream_tools must still drop it.
    monkeypatch.setattr(server, "ALLOWED_TOOLS", server.ALLOWED_TOOLS | {"place_order"})
    kept = server.filter_upstream_tools([_tool("place_order")])
    assert kept == []


def test_envelope_shape():
    envelope = server._envelope({"quantity": 10})
    assert envelope["source"] == "kite"
    assert "as_of" in envelope
    assert envelope["data"] == {"quantity": 10}


def test_call_tool_rejects_denied_tool_without_touching_network():
    with pytest.raises(ValueError, match="place_order"):
        asyncio.run(server.call_tool("place_order", {}))


def test_call_tool_rejects_unknown_tool_without_touching_network():
    with pytest.raises(ValueError, match="not_a_real_tool"):
        asyncio.run(server.call_tool("not_a_real_tool", {}))


def test_persisted_session_id_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SESSION_ID_FILE", tmp_path / "nested" / "kite_gateway_session_id.json")
    assert server._read_persisted_session_id() is None  # file doesn't exist yet
    server._write_persisted_session_id("abc-123")
    assert server._read_persisted_session_id() == "abc-123"


def test_write_persisted_session_id_is_owner_only(monkeypatch, tmp_path):
    # The session id is a bearer credential for Kite's full MCP surface
    # (including the order-placing tools this gateway never forwards) —
    # must not be group/other readable.
    path = tmp_path / "kite_gateway_session_id.json"
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    server._write_persisted_session_id("abc-123")
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_write_persisted_session_id_tightens_preexisting_loose_permissions(monkeypatch, tmp_path):
    path = tmp_path / "kite_gateway_session_id.json"
    path.write_text("{}")
    path.chmod(0o644)
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    server._write_persisted_session_id("abc-123")
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_write_persisted_session_id_chmods_before_writing_content(monkeypatch, tmp_path):
    # Permissions must be tightened before content is written, not after —
    # otherwise a pre-existing loose-permission file would briefly hold the
    # freshly-written secret at the old permissions. Simulated by making the
    # write itself fail and asserting the chmod already landed regardless.
    path = tmp_path / "kite_gateway_session_id.json"
    path.write_text("{}")
    path.chmod(0o644)
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)

    real_write = os.write

    def failing_write(fd, data):
        assert oct(os.fstat(fd).st_mode)[-3:] == "600"  # chmod must already have happened
        raise OSError("simulated write failure")

    monkeypatch.setattr(server.os, "write", failing_write)
    with pytest.raises(OSError, match="simulated write failure"):
        server._write_persisted_session_id("abc-123")
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_read_persisted_session_id_tolerates_corrupt_file(monkeypatch, tmp_path):
    path = tmp_path / "kite_gateway_session_id.json"
    path.write_text("not valid json")
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    assert server._read_persisted_session_id() is None


def test_read_persisted_session_id_tolerates_non_string_saved_at(monkeypatch, tmp_path):
    # Valid JSON, wrong type (e.g. a hand-edited or malformed file) —
    # datetime.fromisoformat(123) raises TypeError, not ValueError; must
    # still be tolerated like any other corrupt-file case, not crash.
    path = tmp_path / "kite_gateway_session_id.json"
    path.write_text(json.dumps({"session_id": "abc-123", "saved_at": 123}))
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    assert server._read_persisted_session_id() is None


def test_read_persisted_session_id_tolerates_missing_saved_at(monkeypatch, tmp_path):
    # A file from before the TTL field existed, or hand-edited — treat as
    # untrustworthy rather than crash or assume it's still fresh.
    path = tmp_path / "kite_gateway_session_id.json"
    path.write_text(json.dumps({"session_id": "abc-123"}))
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    assert server._read_persisted_session_id() is None


def test_read_persisted_session_id_rejects_expired_entry(monkeypatch, tmp_path):
    path = tmp_path / "kite_gateway_session_id.json"
    stale = datetime.now(server.IST) - server.SESSION_ID_TTL - timedelta(minutes=1)
    path.write_text(json.dumps({"session_id": "abc-123", "saved_at": stale.isoformat()}))
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    assert server._read_persisted_session_id() is None


def test_read_persisted_session_id_accepts_entry_within_ttl(monkeypatch, tmp_path):
    path = tmp_path / "kite_gateway_session_id.json"
    fresh = datetime.now(server.IST) - server.SESSION_ID_TTL + timedelta(minutes=1)
    path.write_text(json.dumps({"session_id": "abc-123", "saved_at": fresh.isoformat()}))
    monkeypatch.setattr(server, "SESSION_ID_FILE", path)
    assert server._read_persisted_session_id() == "abc-123"


def test_ensure_session_id_reuses_persisted_id_without_connecting(monkeypatch, tmp_path):
    session_file = tmp_path / "kite_gateway_session_id.json"
    monkeypatch.setattr(server, "SESSION_ID_FILE", session_file)
    server._write_persisted_session_id("persisted-session-id")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not connect when a persisted session id exists")

    monkeypatch.setattr(server, "streamablehttp_client", fail_if_called)

    upstream = server._Upstream()
    anyio.run(upstream._ensure_session_id)
    assert upstream._session_id == "persisted-session-id"


def test_ensure_session_id_is_race_safe(monkeypatch, tmp_path):
    calls = {"connects": 0, "initializes": 0}
    # Isolate from any real persisted session on disk so this test exercises
    # the initialize() race path, not a short-circuit through a stale file.
    monkeypatch.setattr(server, "SESSION_ID_FILE", tmp_path / "kite_gateway_session_id.json")

    class FakeClientSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def initialize(self):
            calls["initializes"] += 1
            # Widen the race window: without the lock, both concurrent
            # callers would already have passed the "is None" check by now.
            await anyio.sleep(0.05)

    @asynccontextmanager
    async def fake_streamablehttp_client(url, headers=None, terminate_on_close=True):
        calls["connects"] += 1
        yield (None, None, lambda: "fake-session-id")

    monkeypatch.setattr(server, "ClientSession", FakeClientSession)
    monkeypatch.setattr(server, "streamablehttp_client", fake_streamablehttp_client)

    upstream = server._Upstream()

    async def run_two_concurrent_first_calls():
        async with anyio.create_task_group() as tg:
            tg.start_soon(upstream._ensure_session_id)
            tg.start_soon(upstream._ensure_session_id)

    anyio.run(run_two_concurrent_first_calls)

    assert calls["initializes"] == 1
    assert calls["connects"] == 1
    assert upstream._session_id == "fake-session-id"
