---
name: portfolio-health-check
description: Use when the user asks for a portfolio-wide health check, concentration review, or overall winners/losers across their real brokerage holdings — e.g. "how's my portfolio doing", "am I too concentrated in anything", "what are my biggest winners/losers". Not for single-stock research (no portfolio context needed) or order placement (out of scope by policy).
expected_outputs:
  - "workspaces/{workspace}/results/health_check_{date}.json"
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

1. **Confirm a workspace.** This skill writes into the current workspace's
   `data/`, `results/`, and `notes.md`. If no workspace is open, ask the
   user to open or name one first rather than writing to repo root.

2. **Fetch real holdings from the connected broker.** Currently
   `kite_gateway` — call `kite_gateway.get_holdings` (read-only by
   construction: the order-placing/-modifying tools aren't in
   `kite_gateway`'s tool surface at all, see docs/vision.md §5). Save the
   raw result to `data/holdings_<YYYY-MM-DD>.json` in the workspace.

3. **Run the computation, not the model.** From the workspace directory:

   ```
   uv run python <path-to-this-skill>/scripts/health_check.py data/holdings_<date>.json
   ```

   This writes `results/health_check_<date>.json` (total value/invested/P&L,
   per-position weight, top concentration, top winners/losers by P&L%, full
   position table). Read numbers from that file only — never restate a
   holdings figure from memory or eyeball a percentage.

4. **Offer a deeper dive, don't force one.** If any single position is above
   roughly 15% portfolio weight, or the user asks about a specific holding,
   offer (don't auto-run) a volatility/drawdown deep dive:

   - Fetch ~1yr daily bars: `india_price.get_daily_ohlcv(symbol, from_date, to_date)`.
   - Save to `data/<symbol>_ohlcv_1y.json`, then run:
     ```
     uv run python <path-to-this-skill>/scripts/volatility.py data/<symbol>_ohlcv_1y.json
     ```
     which writes `results/<symbol>_volatility_<date>.json` (1yr return, max
     drawdown + dates, daily/annualized volatility, worst single day).
   - Whether a concentrated position is "deliberate or should be trimmed" is
     the user's conviction call, not this skill's to make — present the
     numbers (drawdown history, volatility vs. a diversified book) and ask,
     don't conclude on their behalf. If the user says they're undecided,
     record that verbatim in notes and don't re-push next session.

5. **Update workspace notes.md** per docs/vision.md's Working Notes
   convention — read current content first, merge, don't overwrite.
   Include: key findings (total P&L, concentration risk, winners/losers —
   numbers, not vibes), a pointer to the computed result files, and an
   open-thread entry for anything the user hasn't decided yet.

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
