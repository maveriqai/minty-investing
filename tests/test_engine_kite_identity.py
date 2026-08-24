"""Tests for engine/kite_identity.py — the compare-and-flag half of the
account-identity mismatch check (issue #19). Parsing-shape and
fail-open-on-ambiguity behavior only; the hooks that consume this module
are tested in tests/test_engine_claude_harness.py.
"""

import json

from engine import kite_status
from engine.kite_identity import IdentityGuardState, user_id_from_get_profile_response


def test_user_id_from_flat_data_envelope():
    assert user_id_from_get_profile_response({"source": "kite", "data": {"user_id": "AB1234"}}) == "AB1234"


def test_user_id_from_data_as_content_block_list():
    # The shape a real get_profile call actually returns when
    # structuredContent is absent — see kite_status.py's own
    # anchor_user_id docstring, live-confirmed 2026-08-20 (#5/#7).
    profile_text = json.dumps({"user_id": "QK0438", "user_name": "Test User"})
    tool_response = {"source": "kite", "data": [{"type": "text", "text": profile_text}]}
    assert user_id_from_get_profile_response(tool_response) == "QK0438"


def test_user_id_from_raw_mcp_content_envelope():
    # A plausible alternative shape: tool_response carries the raw MCP
    # CallToolResult ({"content": [...]}), with our own envelope JSON
    # inside the text block. Not live-confirmed — see the module
    # docstring — but the parser should handle it if it occurs.
    envelope_text = json.dumps({"source": "kite", "data": {"user_id": "CD5678"}})
    tool_response = {"content": [{"type": "text", "text": envelope_text}]}
    assert user_id_from_get_profile_response(tool_response) == "CD5678"


def test_user_id_from_unrecognized_shape_returns_none():
    assert user_id_from_get_profile_response("not a dict") is None
    assert user_id_from_get_profile_response({}) is None
    assert user_id_from_get_profile_response({"content": "not valid json"}) is None
    assert user_id_from_get_profile_response({"data": [{"type": "image"}]}) is None


def test_record_profile_response_no_mismatch_when_ids_match(monkeypatch, tmp_path):
    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text(json.dumps({"source": "kite", "data": {"user_id": "AB1234"}}))

    state = IdentityGuardState()
    state.record_profile_response({"data": {"user_id": "AB1234"}})

    assert state.mismatch is False
    assert state.live_user_id == "AB1234"


def test_record_profile_response_flags_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text(json.dumps({"source": "kite", "data": {"user_id": "AB1234"}}))

    state = IdentityGuardState()
    state.record_profile_response({"data": {"user_id": "ZZ9999"}})

    assert state.mismatch is True
    assert state.live_user_id == "ZZ9999"


def test_record_profile_response_no_mismatch_when_no_anchor_exists_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")

    state = IdentityGuardState()
    state.record_profile_response({"data": {"user_id": "AB1234"}})

    assert state.mismatch is False


def test_record_profile_response_leaves_state_unchanged_on_unparseable_response(monkeypatch, tmp_path):
    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text(json.dumps({"source": "kite", "data": {"user_id": "AB1234"}}))

    state = IdentityGuardState()
    state.record_profile_response("garbage, not a dict")

    assert state.mismatch is False
    assert state.live_user_id is None


def test_mismatch_never_resets_to_false_once_confirmed(monkeypatch, tmp_path):
    monkeypatch.setattr(kite_status, "ACCOUNT_IDENTITY_FILE", tmp_path / "account_identity.json")
    (tmp_path / "account_identity.json").write_text(json.dumps({"source": "kite", "data": {"user_id": "AB1234"}}))

    state = IdentityGuardState()
    state.record_profile_response({"data": {"user_id": "ZZ9999"}})
    assert state.mismatch is True

    # A later matching call must not clear the flag — resolving a real
    # mismatch is a deliberate, out-of-band step (deleting the anchor
    # file), never something a later tool call should silently undo.
    state.record_profile_response({"data": {"user_id": "AB1234"}})
    assert state.mismatch is True
