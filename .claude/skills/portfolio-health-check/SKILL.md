---
name: portfolio-health-check
description: Use when the user asks for a portfolio-wide health check, concentration review, or overall winners/losers across their real brokerage holdings — e.g. "how's my portfolio doing", "am I too concentrated in anything", "what are my biggest winners/losers". Not for single-stock research (no portfolio context needed), order placement (out of scope by policy), or a market-moved daily recap — phrases like "what happened overnight" or "give me the morning digest" belong to morning-digest, not here.
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
   broker.** Call the `check_identity_match` tool (no arguments) — a
   deterministic engine tool that calls `get_profile` itself and compares
   it against `data/account_identity.json` (an install-wide anchor at the
   **repo root**, not workspace content, shared with morning-digest).
   Don't `Read` the anchor file or call `kite_gateway.get_profile` yourself
   for this — the comparison is engine-computed, not something to reason
   about from raw JSON. Branch on its `status` field:
   - **`"no_anchor"` or `"match"`:** proceed.
   - **`"mismatch"`:** **Stop** — report plainly that a different Zerodha
     account is connected than expected (cite the tool's own
     `anchor_user_id`/`live_user_id`), and don't fetch or overwrite the
     workspace's `data/holdings_<date>.json`. The anchor is engine-managed
     and write-once — this stays flagged every run until a human resolves
     it by hand, not something fixable from inside a conversation.
   - **An error result** (e.g. no active Kite session): handle it the same
     way you'd handle a `get_profile` failure — present the login flow.

   Currently `kite_gateway` is the only connected broker — call
   `fetch_holdings(workspace_root=...)`, not `kite_gateway.get_holdings`
   directly (`get_holdings` itself is blocked — issue #46).
   `fetch_holdings` fetches and saves `data/holdings_<YYYY-MM-DD>.json` in
   one step and reports back only a holdings count, never the holdings
   themselves — no separate save step, and nothing to read from its
   response.

3. **Run the computation, not the model** — call the `run_health_check`
   tool (not Bash) with `workspace_root` set to the exact active-workspace
   path and `holdings_file` set to the path you just saved (e.g.
   `data/holdings_<date>.json`).

   This writes `results/health_check_<date>.json` (total value/invested/P&L,
   per-position weight, an asset-class breakdown — equity/ETF/G-Sec/other —
   top concentration, top winners/losers by P&L%, full position table). Read
   numbers from that file only — never restate a holdings figure from
   memory or eyeball a percentage.

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
   different filename or location for it. Mention this save in your reply
   — a short line like "saved to `notes.md`" — so the user knows it
   happened (issue #68).

6. **Don't write your own Sources footer or SEBI disclaimer.** The engine
   appends both automatically — built from whatever was actually captured
   this turn — once your reply text is complete. Writing one yourself just
   duplicates it (issue #27).

## Guardrails

- Never call Kite's order-placing/modifying tools — they aren't in
  `kite_gateway`'s tool surface at all; only read-only calls are possible.
  Fetch holdings via `fetch_holdings`, not `kite_gateway.get_holdings`
  directly — that raw tool is blocked (issue #46).
- Never compute P&L, weight, or volatility by LLM arithmetic — always
  through `scripts/health_check.py` / `scripts/volatility.py` or an
  equivalent one-off script, never inline reasoning.
- Sector breakdown isn't fully available yet — `kite_gateway.get_holdings`
  has no sector field, and the instruments master's own sector coverage is
  partial (Nifty 500 constituents only, see `mcp/common/instruments.py`).
  Don't guess sectors; say what's covered and what isn't.
- Asset-class classification (`asset_class_breakdown` in the health-check
  output) is symbol-pattern based, not a real data source — ETF suffix
  (`*BEES`), G-Sec suffixes (`*-GS`/`*-SG`), and a digit-leading-symbol
  heuristic for other bonds that don't use those suffixes. It isn't
  exhaustive; anything bucketed as "Other (unclassified)" should be called
  out to the user as such, never silently narrated as equity.
