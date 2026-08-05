"""Unit tests for skills/morning-digest/scripts/surveillance_check.py::compute.

Pure function tests against synthetic holdings + surveillance-payload
fixtures — no network, no Kite session.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sc = _load(
    "surveillance_check",
    Path(__file__).parent.parent / ".claude" / "skills" / "morning-digest" / "scripts" / "surveillance_check.py",
)

HOLDINGS = [
    {"tradingsymbol": "STOCKA", "quantity": 10},
    {"tradingsymbol": "INFY", "quantity": 5},
]


def test_finds_hit_nested_under_data_data():
    asm_payload = {"source": "NSE reportASM", "data": {"data": [{"symbol": "STOCKA"}, {"symbol": "BAJAJCON"}]}}
    gsm_payload = {"source": "NSE reportGSM", "data": {"data": []}}
    result = sc.compute(HOLDINGS, asm_payload, gsm_payload)
    assert result["asm_hits"] == ["STOCKA"]
    assert result["gsm_hits"] == []
    assert result["held_count"] == 2


def test_no_hits_when_held_symbols_absent():
    asm_payload = {"data": {"data": [{"symbol": "SOMEOTHER"}]}}
    gsm_payload = {"data": {"data": [{"symbol": "ANOTHERONE"}]}}
    result = sc.compute(HOLDINGS, asm_payload, gsm_payload)
    assert result["asm_hits"] == []
    assert result["gsm_hits"] == []


def test_error_envelope_yields_no_hits_not_a_crash():
    asm_payload = {"data": {"error": "circuit open"}}
    gsm_payload = {"data": {"error": "circuit open"}}
    result = sc.compute(HOLDINGS, asm_payload, gsm_payload)
    assert result["asm_hits"] == []
    assert result["gsm_hits"] == []


def test_cli_unwraps_envelope_wrapped_holdings_file(tmp_path):
    """Live-found 2026-08-04: kite_gateway.get_holdings' raw captured result
    is a {"source","as_of","data"} envelope (same shape health_check.py,
    volatility.py, and digest_math.py already unwrap) — the CLI here read
    it raw, so `h["tradingsymbol"]` crashed against the envelope's own
    "source"/"as_of"/"data" keys, and a live digest run had to work around
    it by hand-building a bare-list holdings file instead of trusting this
    script, defeating the point of a deterministic check."""
    holdings_path = tmp_path / "holdings.json"
    holdings_path.write_text(
        json.dumps({"source": "kite_gateway", "as_of": "2026-08-04", "data": HOLDINGS})
    )
    asm_path = tmp_path / "asm.json"
    asm_path.write_text(json.dumps({"data": [{"symbol": "STOCKA"}]}))
    gsm_path = tmp_path / "gsm.json"
    gsm_path.write_text(json.dumps({"data": []}))

    script_path = Path(__file__).parent.parent / ".claude" / "skills" / "morning-digest" / "scripts" / "surveillance_check.py"
    result = subprocess.run(
        [sys.executable, str(script_path), str(holdings_path), str(asm_path), str(gsm_path), "2026-08-04"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    output = json.loads((tmp_path / "results" / "surveillance_flags_2026-08-04.json").read_text())
    assert output["asm_hits"] == ["STOCKA"]
    assert output["held_count"] == 2
    assert "held=2" in result.stdout
