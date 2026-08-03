"""Deterministic surveillance-list intersection for morning-digest step 6.

Checks which held symbols appear on NSE's ASM/GSM surveillance lists, in
code rather than an ad-hoc grep against raw tool-result files. Added
2026-07-09 after a real headless-run failure: with no deterministic script
for this step, the model resorted to raw Bash grep/shell loops that weren't
covered by run_digest.sh's ALLOWED_TOOLS, and the resulting permission
denials sometimes made it stall instead of finishing the digest. This
mirrors digest_math.py's pattern so step 6 has the same reliable, allowlisted
path step 5 already has.

NSE's ASM/GSM payloads nest their symbol lists differently across endpoints
and have changed shape before (see mcp/india_filings/server.py's
module docstring) — rather than assume one fixed key path, this walks the
whole envelope and collects every "symbol" value found, so it keeps working
even if the nesting shifts.

Usage:
  uv run python surveillance_check.py data/holdings_2026-07-09.json \
    data/surveillance_asm_2026-07-09.json data/surveillance_gsm_2026-07-09.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _extract_symbols(payload: object) -> set[str]:
    """Walk an NSE surveillance envelope, collecting every 'symbol' value found."""
    found: set[str] = set()
    if isinstance(payload, dict):
        sym = payload.get("symbol")
        if isinstance(sym, str):
            found.add(sym.strip().upper())
        for value in payload.values():
            found |= _extract_symbols(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _extract_symbols(item)
    return found


def compute(holdings: list[dict], asm_payload: object, gsm_payload: object) -> dict:
    held_symbols = sorted({h["tradingsymbol"].strip().upper() for h in holdings})
    asm_symbols = _extract_symbols(asm_payload)
    gsm_symbols = _extract_symbols(gsm_payload)
    return {
        "held_count": len(held_symbols),
        "asm_hits": sorted(s for s in held_symbols if s in asm_symbols),
        "gsm_hits": sorted(s for s in held_symbols if s in gsm_symbols),
    }


if __name__ == "__main__":
    holdings_path, asm_path, gsm_path = (Path(p) for p in sys.argv[1:4])
    holdings = json.loads(holdings_path.read_text())
    asm_payload = json.loads(asm_path.read_text())
    gsm_payload = json.loads(gsm_path.read_text())

    result = compute(holdings, asm_payload, gsm_payload)
    result["source"] = "india_filings.get_surveillance_list (ASM, GSM)"
    result["input_files"] = [holdings_path.name, asm_path.name, gsm_path.name]

    # Use the ASM file's date, not the holdings file's — the holdings
    # snapshot can be a stale fallback (see jobs/README.md's known
    # limitation) while the surveillance data is always fetched fresh for
    # today's run.
    date_tag = asm_path.stem.replace("surveillance_asm_", "")
    out_dir = Path.cwd() / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"surveillance_flags_{date_tag}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(f"held={result['held_count']} asm_hits={result['asm_hits']} gsm_hits={result['gsm_hits']}")
