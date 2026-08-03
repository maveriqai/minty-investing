"""Unit tests for skills/morning-digest/scripts/surveillance_check.py::compute.

Pure function tests against synthetic holdings + surveillance-payload
fixtures — no network, no Kite session.
"""

import importlib.util
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
