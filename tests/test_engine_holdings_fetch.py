"""Unit tests for engine/holdings_fetch.py's fetch_holdings tool — the fix
for issue #46 (kite_gateway.get_holdings on a 96-holding real account
exceeds the Claude Agent SDK's tool-result size limit, so the SDK
substitutes a plain-text redirect and the capture is silently never
written). fetch_holdings fetches in-process and never hands the raw
payload back through the model, so its own return value must always stay
small regardless of how many holdings the upstream call reports.
"""

import asyncio
import json

from engine import holdings_fetch
from engine.time_ist import today_ist
from mcp import types

_TODAY = today_ist()


def _run(coro):
    return asyncio.run(coro)


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")


def _envelope_result(data, is_error=False) -> types.CallToolResult:
    envelope = {"source": "kite", "as_of": "2026-08-28 10:00 IST", "data": data}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(envelope))],
        isError=is_error,
    )


def _patch_kite_call(monkeypatch, result: types.CallToolResult):
    async def fake_call_tool(name, arguments):
        assert name == "get_holdings"
        assert arguments == {}
        return result

    monkeypatch.setattr(holdings_fetch._kite_gateway_server, "call_tool", fake_call_tool)


def test_writes_holdings_file_and_reports_only_a_short_count(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)

    holdings = [{"tradingsymbol": f"STOCK{i}", "quantity": 1} for i in range(96)]
    _patch_kite_call(monkeypatch, _envelope_result(holdings))

    result = _run(holdings_fetch._handler({"workspace_root": str(workspace)}))

    saved = workspace / "data" / f"holdings_{_TODAY}.json"
    assert saved.exists()
    assert json.loads(saved.read_text())["data"] == holdings

    text = result["content"][0]["text"]
    assert not result.get("is_error")
    assert "96 holdings" in text
    assert len(text) < 200  # never the payload, just a status
    assert "tradingsymbol" not in text


def test_large_synthetic_payload_never_round_trips_through_the_return_value(tmp_path, monkeypatch):
    """The whole point of this tool: a payload far larger than the SDK's
    real tool-result ceiling must still produce a short, bounded response —
    proof by construction, since the return value never contains `data` at
    all, only a count derived from it."""
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)

    holdings = [
        {
            "tradingsymbol": f"STOCK{i}",
            "exchange": "NSE",
            "isin": f"INE{i:06d}01",
            "quantity": 10,
            "average_price": 123.45,
            "last_price": 130.0,
            "close_price": 128.0,
            "pnl": 65.5,
        }
        for i in range(200)
    ]
    _patch_kite_call(monkeypatch, _envelope_result(holdings))

    result = _run(holdings_fetch._handler({"workspace_root": str(workspace)}))

    assert len(result["content"][0]["text"]) < 200
    assert "200 holdings" in result["content"][0]["text"]


def test_invalid_workspace_root_is_rejected_before_any_fetch(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()

    called = False

    async def fake_call_tool(name, arguments):
        nonlocal called
        called = True
        return _envelope_result([])

    monkeypatch.setattr(holdings_fetch._kite_gateway_server, "call_tool", fake_call_tool)

    result = _run(holdings_fetch._handler({"workspace_root": str(outside)}))

    assert result["is_error"] is True
    assert not called


def test_no_active_session_error_is_forwarded_recognizably(tmp_path, monkeypatch):
    """morning-digest's SKILL.md falls back to a cached holdings file only
    on a real 'no active session' failure, never on an account-mismatch
    denial (that's caught earlier, by the identity PreToolUse hook, before
    this handler ever runs) — so Kite's own error text must survive
    recognizably, not get replaced with fetch_holdings' own generic
    wording. The fake result here matches the real shape
    mcp/kite_gateway/server.py's call_tool actually produces on error
    (issue #50 follow-up) — a JSON-serialized {"source","as_of",
    "data":{"error":[...]}} envelope, not a plain string — so this also
    proves the envelope gets unwrapped down to just the human-readable
    message, not forwarded whole."""
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)

    envelope_text = json.dumps(
        {
            "source": "kite",
            "as_of": "2026-08-29 22:10 IST",
            "data": {"error": [{"type": "text", "text": "Please log in first using the login tool"}]},
        },
        indent=2,
    )
    error_result = types.CallToolResult(
        content=[types.TextContent(type="text", text=envelope_text)],
        isError=True,
    )
    _patch_kite_call(monkeypatch, error_result)

    result = _run(holdings_fetch._handler({"workspace_root": str(workspace)}))

    assert result["is_error"] is True
    assert "Please log in first using the login tool" in result["content"][0]["text"]
    assert '"source"' not in result["content"][0]["text"]
    assert not (workspace / "data" / f"holdings_{_TODAY}.json").exists()


def test_untrustworthy_result_is_not_saved_and_is_reported_honestly(tmp_path, monkeypatch):
    """An error-shaped {"data": {"error": ...}} envelope (not the SDK-size
    redirect case, but the same untrustworthy-capture guard) must never be
    written to data/holdings_<date>.json — mirrors
    tool_capture._is_untrustworthy_capture's existing coverage."""
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)

    # isError False (Kite call itself "succeeded"), but the payload is the
    # untrustworthy error-envelope shape _is_untrustworthy_capture rejects.
    _patch_kite_call(monkeypatch, _envelope_result({"error": "thin coverage"}, is_error=False))

    result = _run(holdings_fetch._handler({"workspace_root": str(workspace)}))

    assert result["is_error"] is True
    assert not (workspace / "data" / f"holdings_{_TODAY}.json").exists()


def test_wrapped_single_content_block_response_is_unwrapped_before_saving(tmp_path, monkeypatch):
    """Live-observed 2026-08-29 (issue #49): Kite's get_holdings can come
    back with `data` as a single wrapped content block whose own `text`
    field holds the real flat holdings list, serialized as a string,
    instead of the normal flat list directly. Must be unwrapped before
    saving/counting, not saved (or counted) as-is."""
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)

    real_holdings = [{"tradingsymbol": f"STOCK{i}", "quantity": 10} for i in range(96)]
    wrapped_data = [
        {"type": "text", "text": json.dumps(real_holdings), "annotations": None, "meta": None}
    ]
    _patch_kite_call(monkeypatch, _envelope_result(wrapped_data))

    result = _run(holdings_fetch._handler({"workspace_root": str(workspace)}))

    saved = workspace / "data" / f"holdings_{_TODAY}.json"
    assert saved.exists()
    saved_text = saved.read_text()
    assert json.loads(saved_text)["data"] == real_holdings
    # Regression check, live-observed 2026-08-29: re-serializing the
    # unwrapped envelope compactly (no indent) collapsed the whole file to
    # one line, breaking any later offset/limit Read of it (e.g.
    # thesis-tracker looking up a single symbol) regardless of range.
    assert saved_text.count("\n") > 10

    text = result["content"][0]["text"]
    assert not result.get("is_error")
    assert "96 holdings" in text


def test_normalize_holdings_data_leaves_genuine_data_shapes_untouched():
    real_holdings = [{"tradingsymbol": "STOCK0", "quantity": 10}]
    assert holdings_fetch._normalize_holdings_data(real_holdings) == real_holdings
    assert holdings_fetch._normalize_holdings_data([]) == []
    # A single content block whose text isn't valid JSON, or doesn't decode
    # to a list, must fall back to the original value rather than raising.
    not_json = [{"type": "text", "text": "not json"}]
    assert holdings_fetch._normalize_holdings_data(not_json) == not_json
    not_a_list = [{"type": "text", "text": json.dumps({"foo": "bar"})}]
    assert holdings_fetch._normalize_holdings_data(not_a_list) == not_a_list


def test_holdings_count_handles_non_list_data():
    assert holdings_fetch._holdings_count(json.dumps({"source": "kite", "as_of": "x", "data": "not-a-list"})) is None
    assert holdings_fetch._holdings_count("not json at all") is None
    assert holdings_fetch._holdings_count(json.dumps({"data": [1, 2, 3]})) == 3
