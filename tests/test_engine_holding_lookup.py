"""Unit tests for engine/holding_lookup.py's get_holding_for_symbol tool —
the fix for issue #50 (thesis-tracker had no way to pull a single symbol's
holding out of the cached holdings_<date>.json file, since the file itself
is too large to Read reliably and kite_gateway.get_holdings is blocked).
Unlike fetch_holdings, this tool never calls Kite — it's a pure read of
whatever fetch_holdings already wrote for today, so tests just pre-write
the cache file directly.
"""

import asyncio
import json

from engine import holding_lookup
from engine.time_ist import today_ist

_TODAY = today_ist()


def _run(coro):
    return asyncio.run(coro)


def _patch_roots(monkeypatch, tmp_path):
    import engine.workspace as workspace_module

    monkeypatch.setattr(workspace_module, "WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(workspace_module, "DEV_WORKSPACES_ROOT", tmp_path / ".dev-workspaces")


def _write_holdings(workspace, holdings, *, as_of="2026-08-29 15:29 IST"):
    data_dir = workspace / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    envelope = {"source": "kite", "as_of": as_of, "data": holdings}
    (data_dir / f"holdings_{_TODAY}.json").write_text(json.dumps(envelope, indent=2))


def test_found_exact_case_match(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    _write_holdings(
        workspace,
        [
            {"tradingsymbol": "RELIANCE", "quantity": 10, "average_price": 2500.0},
            {"tradingsymbol": "TCS", "quantity": 5, "average_price": 3800.0},
        ],
    )

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(workspace)}))

    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "found"
    assert payload["holding"]["quantity"] == 10
    assert payload["holding"]["average_price"] == 2500.0
    assert payload["as_of"] == "2026-08-29 15:29 IST"


def test_found_case_insensitive_match(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    _write_holdings(workspace, [{"tradingsymbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}])

    result = _run(holding_lookup._handler({"symbol": "reliance", "workspace_root": str(workspace)}))

    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "found"
    assert payload["symbol"] == "RELIANCE"


def test_not_held_is_a_normal_result_not_an_error(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    _write_holdings(workspace, [{"tradingsymbol": "TCS", "quantity": 5, "average_price": 3800.0}])

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(workspace)}))

    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "not_held"
    assert payload["symbol"] == "RELIANCE"


def test_missing_cache_returns_no_cache_status_not_an_error(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(workspace)}))

    assert not result.get("is_error")
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "no_cache"
    assert payload["date"] == _TODAY


def test_corrupted_cache_file_is_an_error(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data"
    data_dir.mkdir(parents=True)
    (data_dir / f"holdings_{_TODAY}.json").write_text("{not valid json")

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(workspace)}))

    assert result["is_error"] is True
    assert "fetch_holdings" in result["content"][0]["text"]


def test_wrong_shape_cache_file_is_an_error(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data"
    data_dir.mkdir(parents=True)
    (data_dir / f"holdings_{_TODAY}.json").write_text(json.dumps({"source": "kite", "as_of": _TODAY}))

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(workspace)}))

    assert result["is_error"] is True
    assert "fetch_holdings" in result["content"][0]["text"]


def test_invalid_workspace_root_is_rejected(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()

    result = _run(holding_lookup._handler({"symbol": "RELIANCE", "workspace_root": str(outside)}))

    assert result["is_error"] is True
