"""Unit tests for engine/identity_check.py's check_identity_match tool —
issue #48. Replaces the three skills' own "Read the anchor, call
get_profile, compare in prose" steps with one deterministic tool call;
these tests cover the three real outcomes (no anchor yet / match /
mismatch) plus error-forwarding, and confirm a mismatch found here still
trips the shared IdentityGuardState the PreToolUse deny hook reads
(engine/harnesses/claude_agent_sdk.py's _build_identity_deny_hook).
"""

import asyncio
import json

from engine import identity_check
from engine.kite_identity import IdentityGuardState
from mcp import types


def _run(coro):
    return asyncio.run(coro)


def _patch_identity_file(monkeypatch, path):
    # ACCOUNT_IDENTITY_FILE is imported by value into three modules —
    # each needs its own binding patched (same pattern
    # tests/test_engine_tool_capture.py and tests/test_engine_kite_status.py
    # already use for their own single-module cases).
    monkeypatch.setattr("engine.identity_check.ACCOUNT_IDENTITY_FILE", path)
    monkeypatch.setattr("engine.tool_capture.ACCOUNT_IDENTITY_FILE", path)
    monkeypatch.setattr("engine.kite_status.ACCOUNT_IDENTITY_FILE", path)


def _profile_result(user_id: str, is_error: bool = False) -> types.CallToolResult:
    envelope = {
        "source": "kite",
        "as_of": "2026-08-29 09:00 IST",
        "data": [{"type": "text", "text": json.dumps({"user_id": user_id}), "annotations": None, "meta": None}],
    }
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(envelope))],
        isError=is_error,
    )


def _patch_kite_call(monkeypatch, result: types.CallToolResult):
    async def fake_call_tool(name, arguments):
        assert name == "get_profile"
        assert arguments == {}
        return result

    monkeypatch.setattr(identity_check._kite_gateway_server, "call_tool", fake_call_tool)


def test_no_anchor_yet_writes_it_and_reports_no_anchor_status(tmp_path, monkeypatch):
    identity_file = tmp_path / "data" / "account_identity.json"
    _patch_identity_file(monkeypatch, identity_file)
    _patch_kite_call(monkeypatch, _profile_result("QK0438"))

    state = IdentityGuardState()
    result = _run(identity_check._build_handler(state)({}))

    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"status": "no_anchor", "anchor_user_id": "QK0438", "live_user_id": "QK0438"}
    assert identity_file.exists()
    assert state.mismatch is False


def test_anchor_matches_reports_match(tmp_path, monkeypatch):
    identity_file = tmp_path / "data" / "account_identity.json"
    identity_file.parent.mkdir(parents=True)
    identity_file.write_text(
        json.dumps(
            {"source": "kite", "as_of": "x", "data": [{"type": "text", "text": json.dumps({"user_id": "QK0438"})}]}
        )
    )
    _patch_identity_file(monkeypatch, identity_file)
    _patch_kite_call(monkeypatch, _profile_result("QK0438"))

    state = IdentityGuardState()
    result = _run(identity_check._build_handler(state)({}))

    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "match"
    assert state.mismatch is False


def test_anchor_mismatch_reports_mismatch_and_trips_shared_state(tmp_path, monkeypatch):
    identity_file = tmp_path / "data" / "account_identity.json"
    identity_file.parent.mkdir(parents=True)
    identity_file.write_text(
        json.dumps(
            {"source": "kite", "as_of": "x", "data": [{"type": "text", "text": json.dumps({"user_id": "QK0438"})}]}
        )
    )
    _patch_identity_file(monkeypatch, identity_file)
    _patch_kite_call(monkeypatch, _profile_result("BOGUS999"))

    state = IdentityGuardState()
    result = _run(identity_check._build_handler(state)({}))

    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"status": "mismatch", "anchor_user_id": "QK0438", "live_user_id": "BOGUS999"}
    # The exact promise of #48: a mismatch found via this tool trips the
    # same shared state the PreToolUse deny hook reads, without the model
    # ever calling get_profile directly itself.
    assert state.mismatch is True


def test_no_active_session_error_is_forwarded_and_anchor_untouched(tmp_path, monkeypatch):
    """The fake result here matches the real shape
    mcp/kite_gateway/server.py's call_tool actually produces on error
    (issue #50 follow-up) — a JSON-serialized {"source","as_of",
    "data":{"error":[...]}} envelope, not a plain string — so this also
    proves the envelope gets unwrapped down to just the human-readable
    message, not forwarded whole."""
    identity_file = tmp_path / "data" / "account_identity.json"
    _patch_identity_file(monkeypatch, identity_file)
    envelope_text = json.dumps(
        {
            "source": "kite",
            "as_of": "2026-08-29 09:00 IST",
            "data": {"error": [{"type": "text", "text": "Please log in first using the login tool"}]},
        }
    )
    error_result = types.CallToolResult(
        content=[types.TextContent(type="text", text=envelope_text)],
        isError=True,
    )
    _patch_kite_call(monkeypatch, error_result)

    state = IdentityGuardState()
    result = _run(identity_check._build_handler(state)({}))

    assert result["is_error"] is True
    assert "Please log in first using the login tool" in result["content"][0]["text"]
    assert '"source"' not in result["content"][0]["text"]
    assert not identity_file.exists()
    assert state.mismatch is False
