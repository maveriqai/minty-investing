---
name: portfolio-health-check
description: Use when the user asks for a portfolio-wide health check, concentration review, or overall winners/losers across their real brokerage holdings — e.g. "how's my portfolio doing", "am I too concentrated in anything", "what are my biggest winners/losers". Not for single-stock research (no portfolio context needed) or order placement (out of scope by policy).
expected_outputs:
  - "{workspace}/results/health_check_{date}.json"
deterministic_scripts:
  - id: health_check
    path: scripts/health_check.py
    args:
      - {name: holdings_file, kind: positional, required: true, description: "Path (relative to the workspace) to the saved holdings snapshot, e.g. data/holdings_<date>.json"}
  - id: volatility
    path: scripts/volatility.py
    args:
      - {name: ohlcv_file, kind: positional, required: true, description: "Path (relative to the workspace) to the saved 1yr OHLCV bars, e.g. data/<symbol>_ohlcv_1y.json"}
---

# Portfolio Health Check

Deterministic, grounded read on a real brokerage portfolio: total P&L,
concentration, and winners/losers — plus an optional deeper dive into any
position concentrated enough to warrant one. Money math never happens in
prose; every number in the output traces back to a computed file.

Broker-agnostic by design — Kite (Zerodha), via `kite_gateway`, is the
first and currently only connected broker (see docs/vision.md §4). If more
brokers connect later, step 2 below is the only broker-specific part;
everything after it (computation, notes, output) works from the saved JSON
regardless of which broker it came from.

## Steps

1. **The workspace is already open.** The engine hands you the one active
   workspace's path before you ever see this turn (the "Active workspace:"
   note above) — there's no naming step, and no case where none is open.
   Write into its `data/`, `results/`, and `notes.md` as documented below.

2. **Verify account identity, then fetch real holdings from the connected
   broker.** Read `data/account_identity.json` at the **repo root** first,
   if it exists (not inside the workspace — this is an install-wide
   anchor, not workspace content, shared with morning-digest). Then call
   `kite_gateway.get_profile` and compare its `user_id` against whatever
   you just read.
   - **No anchor file yet:** the engine writes one automatically, the
     moment this call succeeds — nothing for you to do. Just proceed.
   - **Anchor existed and matches:** proceed.
   - **Anchor existed and doesn't match:** **Stop** — report plainly that
     a different Zerodha account is connected than expected, and don't
     fetch or overwrite the workspace's `data/holdings_<date>.json`. Minty
     is a single-account tool by design — a second account's data would
     silently corrupt the cached snapshot rather than raise an error.
     There's no tool call that can update the anchor — it's engine-managed
     and write-once (see `engine/tool_capture.py`) — so this stays flagged
     on every run until a human resolves it by hand (deleting
     `data/account_identity.json`), not something you can fix from inside
     a conversation.

   Currently `kite_gateway` is the only connected broker — call
   `kite_gateway.get_holdings` (read-only by construction: the
   order-placing/-modifying tools aren't in `kite_gateway`'s tool surface
   at all, see docs/vision.md §5). The engine automatically saves the raw
   result to `data/holdings_<YYYY-MM-DD>.json` in the workspace as soon as
   the call returns — no separate save step.

3. **Run the computation, not the model** — call the `run_health_check`
   tool (not Bash) with `workspace_root` set to the exact active-workspace
   path and `holdings_file` set to the path you just saved (e.g.
   `data/holdings_<date>.json`).

   This writes `results/health_check_<date>.json` (total value/invested/P&L,
   per-position weight, top concentration, top winners/losers by P&L%, full
   position table). Read numbers from that file only — never restate a
   holdings figure from memory or eyeball a percentage.

4. **Offer a deeper dive, don't force one.** If any single position is above
   roughly 15% portfolio weight, or the user asks about a specific holding,
   offer (don't auto-run) a volatility/drawdown deep dive:

   - Fetch ~1yr daily bars: `india_price.get_daily_ohlcv(symbol, from_date, to_date)`
     — the engine automatically saves this to `data/<symbol>_ohlcv_1y.json`.
   - Call the `run_volatility` tool (not Bash) with `workspace_root` and
     `ohlcv_file` set to that same path — it writes
     `results/<symbol>_volatility_<date>.json` (1yr return, max drawdown +
     dates, daily/annualized volatility, worst single day).
   - Whether a concentrated position is "deliberate or should be trimmed" is
     the user's conviction call, not this skill's to make — present the
     numbers (drawdown history, volatility vs. a diversified book) and ask,
     don't conclude on their behalf. If the user says they're undecided,
     record that verbatim in notes and don't re-push next session.

5. **Update workspace notes.md** per docs/vision.md's Working Notes
   convention — read the current content first with `Read` (the file may
   not exist yet on a fresh workspace), merge your update into it, don't
   overwrite. Include: key findings (total P&L, concentration risk,
   winners/losers — numbers, not vibes), a pointer to the computed result
   files, and an open-thread entry for anything the user hasn't decided
   yet. Then call the `update_workspace_notes` tool (not `Write`) with
   `workspace_root` and the full merged content — it always saves to
   `notes.md` in the workspace root, so there's no risk of inventing a
   different filename or location for it.

6. **Close every output with a Sources footer** (tool + as-of date for each
   number used) and the exact SEBI disclaimer from docs/vision.md §5.

## Guardrails

- Never call Kite's order-placing/modifying tools — they aren't in
  `kite_gateway`'s tool surface at all; only read-only calls
  (`get_holdings`, `get_positions`, `get_quotes`) are possible.
- Never compute P&L, weight, or volatility by LLM arithmetic — always
  through `scripts/health_check.py` / `scripts/volatility.py` or an
  equivalent one-off script, never inline reasoning.
- Sector breakdown isn't fully available yet — `kite_gateway.get_holdings`
  has no sector field, and the instruments master's own sector coverage is
  partial (Nifty 500 constituents only, see `mcp/common/instruments.py`).
  Don't guess sectors; say what's covered and what isn't.
