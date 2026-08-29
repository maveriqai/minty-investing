---
name: thesis-tracker
description: Use when the user wants to define, update, or review an investment thesis for a specific holding or watchlist name — e.g. "track a thesis on RELIANCE", "update my thesis with this quarter's results", "is my thesis on X still intact". Not for a portfolio-wide check (use portfolio-health-check) or a first-time valuation (thesis-tracker records a target the user states, it doesn't derive one).
license: >
  Derived from anthropics/financial-services-plugins
  (plugins/vertical-plugins/equity-research/skills/thesis-tracker,
  Apache-2.0), via ginlix-ai/LangAlpha's adaptation (skills/thesis-tracker,
  Apache-2.0). Re-adapted for Minty: wired to real Kite MCP holdings and
  Minty's own india_price/india_filings tools instead of FMP, output goes
  to the workspace's own theses/<SYMBOL>.md instead of a Word doc or
  shared notes.md, price-move math runs through the deterministic
  run_thesis_math tool instead of a hand-typed Bash command, and India
  conventions (FY quarters, Ind AS, SEBI disclaimer) applied throughout.
expected_outputs:
  - "{workspace}/results/thesis_*_{date}.json"
  - "{workspace}/theses/*.md"
deterministic_scripts:
  - id: thesis_math
    path: scripts/thesis_math.py
    args:
      - {name: symbol, kind: flag, flag: "--symbol", required: true, description: "NSE trading symbol, e.g. RELIANCE"}
      - {name: entry_price, kind: flag, flag: "--entry-price", required: true, description: "Entry price for the position — real average price from holdings, or today's quote for a watchlist name"}
      - {name: entry_date, kind: flag, flag: "--entry-date", required: true, description: "YYYY-MM-DD the position (or watch) was opened"}
      - {name: current_price, kind: flag, flag: "--current-price", required: true, description: "A fresh price from india_price.get_quote — never reuse a stale number from an earlier step"}
      - {name: as_of, kind: flag, flag: "--as-of", required: false, description: "YYYY-MM-DD, defaults to today if omitted"}
---

# Thesis Tracker

Investment-thesis scorecard for one holding or watchlist name: pillars,
risks, catalysts, and conviction, tracked as a living record inside the
workspace so a later session picks up from where this one left off — not a
one-off writeup. A thesis is only useful if it's falsifiable: track
evidence that weakens it as rigorously as evidence that confirms it.

Money math never happens in prose — any price-based figure (% move since
the thesis was opened, days elapsed) is computed by the `run_thesis_math`
tool, never eyeballed.

## Steps

1. **The workspace is already open.** The engine hands you the one active
   workspace's path before you ever see this turn (the "Active workspace:"
   note above) — there's no naming step, and no case where none is open.
   This skill's own persistent record lives at `theses/<SYMBOL>.md` inside
   it (not `notes.md` — see docs/next-phase-plan.md §4: a thesis is a
   living, per-symbol document, so each symbol gets its own file rather
   than sharing space with everything else).

2. **Define or load the thesis.** Read `theses/<SYMBOL>.md` first (via
   `Read` — it may not exist yet). If it exists, this is an update, not a
   fresh start (go to step 3). If new, capture from the user:
   - **Symbol / company**: NSE trading symbol (e.g. `RELIANCE`), full name.
   - **Position**: long or short. A watchlist name skips the rest of this
     bullet entirely — nothing here touches Kite until the user says they
     actually own it. If this **is** a real holding, verify account
     identity before pulling anything from Kite: read
     `data/account_identity.json` at the **repo root** first, if it exists
     (not inside the workspace — this is an install-wide anchor, shared
     with morning-digest/portfolio-health-check). Then call
     `kite_gateway.get_profile` and compare its `user_id` against whatever
     you just read.
     - **No anchor file yet:** the engine writes one automatically, the
       moment this call succeeds — nothing for you to do. Just proceed.
     - **Anchor existed and matches:** proceed.
     - **Anchor existed and doesn't match:** **Stop** — report plainly
       that a different Zerodha account is connected than expected, and
       don't fetch or use holdings data for this thesis. There's no tool
       call that can update the anchor — it's engine-managed and
       write-once (see `engine/tool_capture.py`) — so this stays flagged
       on every run until a human resolves it by hand (deleting
       `data/account_identity.json`), not something you can fix from
       inside a conversation.

     Once verified, pull actual quantity/average price from
     `kite_gateway.get_holdings` (read-only; never `place_order`/
     `modify_order`/`cancel_order`/GTT tools) rather than asking the user
     to restate what's already known.
   - **Thesis statement**: 1-2 sentences — the core bet.
   - **Key pillars**: 3-5 supporting arguments, each specific enough to be
     checked against a real data point later (not "good company").
   - **Key risks**: 3-5 things that would invalidate the thesis.
   - **Catalysts**: dated or datable upcoming events — results date, AGM,
     product/regulatory milestone. Cross-check
     `india_filings.get_announcements(symbol, from_date, to_date)` **with
     `from_date`/`to_date` explicitly set** for anything already disclosed
     rather than guessing at a date.
   - **Target price**: what the user believes it's worth if the thesis
     plays out. Record what the user states — this skill doesn't derive a
     valuation (no DCF/comps skill exists yet). For a fundamentals pillar
     (P/E, EPS, margins, ROE, revenue/earnings growth), pull real figures
     via `india_price.get_fundamentals(symbol)` — rather than leaving it
     TBD or guessing — **and** `india_screener.get_fundamentals(symbol)`
     for ROCE and the 10/5/3-year/last-year ROE trend, which yfinance
     doesn't have at all. When citing ROE, prefer Screener's `roe_pct`
     over yfinance's `return_on_equity_pct` if both came back — they're
     genuinely different numbers by methodology, not a rounding nuance
     (docs/screener-integration-design.md §2) — and say which source
     you're citing rather than presenting one blended figure. Report gaps
     honestly where a field comes back `None` (common for thinly-covered
     small/micro-caps, and Screener has no markup-stability contract
     either — see §5).
   - **Stop-loss / exit trigger**: what would make the user exit.
   - **Entry price + date**: for the deterministic move-tracking below —
     use the real average price from holdings if it's an existing
     position, else today's `india_price.get_quote([symbol])` close.

3. **Log the new data point** (update path). Ask the user what changed
   (results, a shareholding-pattern filing, management move, competitor
   news) rather than assuming — then, for each pillar it touches, record:
   date, the data point, which pillar it strengthens/weakens/is neutral to,
   and the resulting action (no change / trim / add / exit) and updated
   conviction (High/Medium/Low). Where the data point is a filing, pull it
   for real via `india_filings.get_announcements` or
   `india_filings.get_shareholding_pattern(symbol)` — don't paraphrase from
   memory. When a user-reported figure needs checking against the actual
   filed document (not just the announcement metadata), call
   `india_filings.get_filing_document(url)` with the `attchmntFile` URL from
   `get_announcements` — never Bash/curl (issue #25: that bypassed caching,
   rate-limiting, and auto-capture entirely, and Bash isn't in Minty's tool
   surface at all anymore).

4. **Compute the deterministic move.** Call the `run_thesis_math` tool
   (not Bash) with `workspace_root` set to the exact active-workspace path,
   `symbol`, `entry_price`, `entry_date`, and `current_price` (a fresh
   `india_price.get_quote` call — don't reuse a stale number from an
   earlier step). Writes `results/thesis_<SYMBOL>_<date>.json` with % move
   since entry and days elapsed. Read these figures from the file, not
   from mental arithmetic.

5. **Update the scorecard.** Maintain (in `theses/<SYMBOL>.md`) a running
   table:

   | Pillar | Original Expectation | Current Status | Trend |
   |---|---|---|---|

   plus a catalyst calendar (`Date · Event · Expected Impact · Notes`) and
   the current conviction level. Read the current content first (it may
   not exist yet), merge your update into it, then call the
   `update_workspace_notes` tool with `workspace_root`, `target` set to
   `theses/<SYMBOL>.md`, and the full merged content — never overwrite a
   prior scorecard, and never use `Write` for this file (the tool is the
   only correct way to save it, same as `notes.md` on every other skill).

6. **Never conclude the trim/hold/exit call on the user's behalf.** Present
   the scorecard and the computed move — the decision is theirs. If the
   user has previously said they're undecided on a position, don't
   re-raise it unprompted next session; just make the updated scorecard
   available if they ask.

7. **Don't write your own Sources footer or SEBI disclaimer.** The engine
   appends both automatically — built from whatever was actually captured
   this turn — once your reply text is complete. Writing one yourself just
   duplicates it (issue #27).

## Guardrails

- Never call Kite's order-placing/modifying tools — read-only
  (`get_holdings`, `get_quotes`) only.
- Never compute % move, days elapsed, or any other figure by LLM
  arithmetic — always through the `run_thesis_math` tool.
- Target price and stop-loss are the user's stated inputs, not this
  skill's output — it has no valuation model to derive one from yet.
- FY quarters, not calendar quarters, when dating catalysts/results (e.g.
  "Q3 FY26" = Oct-Dec 2025).
- A thesis should be falsifiable: track disconfirming evidence as
  rigorously as confirming evidence, and don't let conviction drift
  upward just because the price did.
