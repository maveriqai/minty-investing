---
name: screen-indian-stocks
description: Use when the user wants candidate stock ideas from a sector/theme rather than analysis of a name they already gave — e.g. "find undervalued auto sector stocks", "screen IT services for quality names", "what's cheap in FMCG right now". Not for a single-stock deep dive (use red-flag-scan/thesis-tracker) or portfolio-wide review (use portfolio-health-check).
expected_outputs:
  - "{workspace}/results/screen_*_{date}.json"
tool_call_budgets:
  # Audit-only per-turn count (engine/tool_budget.py) — not enforced, just
  # flagged to the engine's own console if exceeded. Set just above the
  # 25-candidate default cap in list_candidates.py's own --limit.
  india_price.get_fundamentals: 25
  india_screener.get_fundamentals: 25
deterministic_scripts:
  - id: list_candidates
    path: scripts/list_candidates.py
    args:
      - {name: industry, kind: positional, required: true, description: "Exact industry label as stored in the instruments master, e.g. 'Automobile and Auto Components' — see step 2 for the full list"}
      - {name: limit, kind: flag, flag: "--limit", required: false, description: "Max candidates to return, defaults to 25 — raise only if the user explicitly asks for a wider sweep"}
      - {name: as_of, kind: flag, flag: "--as-of", required: false, description: "YYYY-MM-DD, defaults to today if omitted — leave this alone so it matches the fundamentals files step 5 looks for"}
  - id: screen_rank
    path: scripts/screen_rank.py
    args:
      - {name: industry, kind: flag, flag: "--industry", required: true, description: "The same industry label passed to list_candidates"}
      - {name: candidates, kind: flag, flag: "--candidates", required: true, description: "Path to the saved candidates file from step 3, e.g. data/candidates_automobile-and-auto-components_<date>.json"}
      - {name: quotes, kind: flag, flag: "--quotes", required: false, description: "Path to the saved live-quotes envelope from step 4's one batched india_price.get_quote call, e.g. data/live_quotes_<date>.json"}
      - {name: as_of, kind: flag, flag: "--as-of", required: false, description: "YYYY-MM-DD, defaults to today — must match whatever date list_candidates and the fundamentals fetches in step 4 actually used"}
---

# Screen Indian Stocks

Sector/theme-based candidate discovery: map a user's theme to a known
industry, build a candidate universe from the local instruments master,
rank on valuation/quality metrics computed in code, and optionally
red-flag-annotate the finalists. **Coverage is Nifty 500 constituents
only** (industry/sector data isn't available for the broader ~22k-row
NSE/BSE universe yet — see `mcp/common/instruments.py`'s module
docstring). This is a starting-point filter, not a valuation model — it
surfaces names worth a closer look, not a buy list.

This skill never touches Kite — it screens a universe, not the user's
holdings, so there's no account-identity check needed the way
morning-digest/portfolio-health-check/thesis-tracker require.

## Steps

1. **The workspace is already open.** The engine hands you the one active
   workspace's path before you ever see this turn (the "Active workspace:"
   note above) — there's no naming step, and no case where none is open.
   Write into its `data/` and `results/` as documented below.

2. **Map the theme to an industry label.** The instruments master's
   industry field uses these exact labels (verified live 2026-08-20):
   Automobile and Auto Components, Capital Goods, Chemicals, Construction,
   Construction Materials, Consumer Durables, Consumer Services,
   Diversified, Fast Moving Consumer Goods, Financial Services, Healthcare,
   Information Technology, Media Entertainment & Publication, Metals &
   Mining, Oil Gas & Consumable Fuels, Power, Realty, Services,
   Telecommunication, Textiles. If the user's phrase doesn't map cleanly
   (e.g. "undervalued auto sector" → "Automobile and Auto Components"),
   confirm the mapping with them rather than guessing silently — a wrong
   label returns zero candidates, not a partial match.

3. **Build the candidate universe.** Call the `run_list_candidates` tool
   (not Bash) with `workspace_root` set to the exact active-workspace path
   and `industry` set to the label from step 2. Writes
   `data/candidates_<industry-slug>_<date>.json`. The 25-candidate default
   cap keeps the next step polite to yfinance — raise `limit` only if the
   user explicitly asks for a wider sweep.

4. **Fetch fundamentals and quotes for every candidate.** Call
   `india_price.get_fundamentals(symbol)` **and**
   `india_screener.get_fundamentals(symbol)` once each per candidate, using
   the bare NSE symbol exactly as it appears in the candidates file (no
   `.NS`/`.BO` suffix) — the engine auto-saves each call to its own
   `data/fundamentals_<SYMBOL>_<date>.json` /
   `data/fundamentals_screener_<SYMBOL>_<date>.json`, so there's nothing to
   manually assemble. Both calls matter: yfinance's ROE comes back null for
   entire sectors (Consumer Cyclical, Energy confirmed live — see #9), and
   `screen_rank.py` prefers Screener's ROE when it's available specifically
   to fix that gap — skipping the `india_screener` call for a candidate
   just means it falls back to yfinance's (possibly null) figure alone.
   Then make **one** batched `india_price.get_quote(symbols)` call covering
   every candidate together — a second `get_quote` call this same turn
   would overwrite the first capture (same filename,
   `data/live_quotes_<date>.json`), silently losing data for whichever
   candidates were only in the first batch.

5. **Run the deterministic ranking.** Call the `run_screen_rank` tool
   (not Bash) with `workspace_root`, `industry`, `candidates` (the exact
   path from step 3), and `quotes` (the exact path from step 4, if you
   made that call). The tool finds each candidate's fundamentals files
   itself from the candidates list and today's date — no need to pass
   fundamentals paths individually. Writes
   `results/screen_<industry-slug>_<date>.json` — `ranked` (composite
   score on ascending trailing P/E + descending ROE, with a
   `high_leverage_flag`, `roe_pct_used`, and `roe_source` — "screener.in"
   or "yfinance", so it's always traceable which figure actually drove the
   ranking) and `excluded` (candidates with no fetched fundamentals, a
   fetch error, or no usable P/E/ROE from either source, each with a
   reason — report these too, don't silently drop them).

6. **Optionally red-flag-annotate the top 5.** For the top 5 entries in
   `ranked`, fetch whatever announcements/surveillance/news you can for
   those specific symbols, then call the `run_red_flag_check` tool for
   each (it's already available regardless of which skill's turn this is
   — see red-flag-scan's own SKILL.md for its exact inputs). This is the
   one place these two skills compound. Skip this step if the user wants a
   fast screen rather than a deep one; say explicitly which you did.

7. **One broader news call for context:**
   `india_news.get_news("<theme phrase>", limit=10)` — sector/theme
   headlines, not per-candidate. Saved automatically to
   `data/news_<theme-phrase>_<date>.json`.

8. **Compose the brief:** state the filter applied (industry label,
   candidate count, cap), then candidate cards for the top of `ranked`
   (symbol, name, P/E, ROE with its `roe_source` noted — e.g. "ROE 13.1%
   (Screener.in)" — leverage flag, last price/day change, any red-flag
   annotations from step 6), then the `excluded` list with reasons if the
   user asks why a name they expected isn't ranked. Close with a Sources
   footer (instruments-master as-of from `list_candidates.py`'s `source`
   field, every `get_fundamentals`/`get_quote`/`get_news` as-of date —
   both india_price's and india_screener's, when the latter was called —
   both `results`/`data` file paths) and the exact SEBI disclaimer from
   docs/vision.md §5.

## Guardrails

- Never call Kite's order-placing/modifying tools — not applicable to
  this skill's tool set (it doesn't touch Kite at all), but the rule
  holds project-wide.
- The ranking is a transparent heuristic (P/E + ROE composite), not a
  valuation model — say so plainly, and never imply a "buy" ranking.
- `debt_to_equity` from `india_price.get_fundamentals` is yfinance's
  percentage convention, not a raw ratio (see
  `.claude/skills/red-flag-scan/scripts/red_flag_check.py`'s
  RELIANCE-based verification) — `screen_rank.py` already accounts for
  this; don't re-interpret the raw number yourself when narrating.
- Candidates with missing/zero/negative P/E or missing ROE are excluded
  from ranking, not scored as bad — say why, don't imply they failed a
  test.
- Nifty 500 coverage only — if the user names a stock outside that
  universe, say it's not covered rather than fabricating a sector for it.
- `return_on_equity_pct` (yfinance) and `screener_roe_pct` (Screener.in)
  are genuinely different numbers by methodology, not a rounding nuance
  (docs/screener-integration-design.md §2) — when citing ROE, say which
  source `roe_source` names, don't present it as one universal figure.
- Screener.in has no published API or markup-stability contract — a
  candidate's `screener_roe_pct` coming back missing may just mean
  Screener's page layout changed for that name, not that the company lacks
  the data.
