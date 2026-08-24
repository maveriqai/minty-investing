---
name: red-flag-scan
description: Use when the user wants a governance/safety-focused check on one specific held or watchlist stock — e.g. "any red flags on STOCKA", "check XYZ for governance issues before I add", "should I be worried about this holding". Not for a portfolio-wide check (use portfolio-health-check).
expected_outputs:
  - "{workspace}/results/red_flags_*_{date}.json"
deterministic_scripts:
  - id: red_flag_check
    path: scripts/red_flag_check.py
    args:
      - {name: symbol, kind: flag, flag: "--symbol", required: true, description: "NSE trading symbol, e.g. RELIANCE"}
      - {name: shareholding, kind: flag, flag: "--shareholding", required: false, description: "Path (relative to the workspace) to the saved shareholding-pattern envelope"}
      - {name: surveillance_asm, kind: flag, flag: "--surveillance-asm", required: false, description: "Path to the saved ASM surveillance-list envelope"}
      - {name: surveillance_gsm, kind: flag, flag: "--surveillance-gsm", required: false, description: "Path to the saved GSM surveillance-list envelope"}
      - {name: announcements, kind: flag, flag: "--announcements", required: false, description: "Path to the saved announcements envelope"}
      - {name: news, kind: flag, flag: "--news", required: false, description: "Path to the saved news envelope"}
      - {name: fundamentals, kind: flag, flag: "--fundamentals", required: false, description: "Path to the saved fundamentals envelope"}
      - {name: fundamentals_screener, kind: flag, flag: "--fundamentals-screener", required: false, description: "Path to the saved Screener.in fundamentals envelope (india_screener.get_fundamentals)"}
      - {name: as_of, kind: flag, flag: "--as-of", required: false, description: "YYYY-MM-DD, defaults to today if omitted"}
---

# Red-Flag Scan

A fixed governance/safety checklist for one NSE-listed stock: surveillance
status, promoter-holding trend, keyword hits in recent filings and news, and
balance-sheet stress thresholds. Every check runs in code
(`scripts/red_flag_check.py`), never as LLM judgment — this skill surfaces
evidence and lets the user weigh it, it never asserts wrongdoing.

## Steps

1. **The workspace is already open.** The engine hands you the one active
   workspace's path before you ever see this turn (the "Active workspace:"
   note above) — there's no naming step, and no case where none is open.
   Read/write its `data/`, `results/`, `notes.md` as documented below.

2. **Resolve the symbol.** `india_price.resolve_symbol` if the user gave a
   company name rather than an exact NSE trading symbol.

3. **Pull the six inputs**, one call each — the engine automatically saves
   each tool's raw result to the workspace's `data/` as soon as the call
   returns, so there's no separate save step:
   - `india_filings.get_shareholding_pattern(symbol)` →
     `data/shareholding_<SYMBOL>_<date>.json`
   - `india_filings.get_surveillance_list("ASM")` →
     `data/surveillance_asm_<date>.json` — market-wide, not per-symbol; safe
     to call every time, the saved file just gets refreshed.
   - `india_filings.get_surveillance_list("GSM")` →
     `data/surveillance_gsm_<date>.json`
   - `india_filings.get_announcements(symbol, from_date, to_date)` **with
     `from_date`/`to_date` explicitly set** to 6-months-back/today
     (`DD-MM-YYYY`, NSE's native format) →
     `data/announcements_<SYMBOL>_<date>.json`. Omitting the dates pulls
     years of history (400KB+), not a bounded window.
   - `india_news.get_news(symbol, limit=10)` → `data/news_<SYMBOL>_<date>.json`
     — once, using the raw NSE tradingsymbol as the query, not also by
     company name (the two return identical results; a second call just
     wastes a fetch and risks a second, uncited file).
   - `india_price.get_fundamentals(symbol)` →
     `data/fundamentals_<SYMBOL>_<date>.json`
   - `india_screener.get_fundamentals(symbol)` →
     `data/fundamentals_screener_<SYMBOL>_<date>.json` — its multi-year ROE
     trend feeds a real check the yfinance fundamentals alone can't (step 4:
     a sharp last-year ROE drop vs. the 3-year average). Screener has no
     markup-stability contract (docs/screener-integration-design.md §5) —
     a missing/errored result here is expected sometimes, same as the
     other four.

   Any one of these can fail or come back with a `data.error` — that's
   expected (NSE outages, thin small-cap coverage, a Screener block), not a
   reason to stop. Missing inputs just skip their checks in the next step.

4. **Run the deterministic scan** by calling the `run_red_flag_check` tool
   — not Bash — with `workspace_root` set to the exact active-workspace
   path, `symbol`, and whichever of `shareholding`/`surveillance_asm`/
   `surveillance_gsm`/`announcements`/`news`/`fundamentals`/
   `fundamentals_screener` step 3 actually fetched, pointed at the exact
   `data/<kind>_<SYMBOL>_<date>.json` path documented there. Omit any input
   that failed or wasn't called — the script handles missing inputs by
   skipping that check, not by crashing. The tool runs the script itself
   and writes `results/red_flags_<SYMBOL>_<date>.json` with `flags`,
   `flag_count`, `checks_performed`, `checks_skipped`, returning that same
   JSON to you.

5. **Compose the brief from the script's output, not from re-reading the
   raw tool data.** For each flag: state the category and quote the
   evidence field verbatim — don't editorialize beyond what the evidence
   says. If `checks_skipped` is non-empty, disclose which checks couldn't
   run and why (upstream error vs. missing data), rather than silently
   presenting a partial scan as complete. If `flag_count` is 0, say so
   plainly — "no flags found" is a real, useful result, not a non-answer.

   Three caveats worth stating explicitly when relevant: (a) keyword hits in
   announcements/news are *mentions*, not confirmed issues — a "related
   party" hit could just as easily be routine disclosure language; (b) the
   fundamentals leverage/liquidity thresholds are fixed heuristics
   (Debt/Equity > 2, current ratio < 1), not sector-adjusted, and yfinance's
   `debt_to_equity` field is occasionally in unexpected units for thinly
   covered small-caps — sanity-check an extreme reading rather than
   reporting it at face value; (c) a `roe_deteriorating` flag (last-year ROE
   below 60% of the 3-year average, from Screener.in's trend data) is also a
   fixed, non-sector-adjusted heuristic — a real signal worth surfacing, not
   a verdict, and it can trip for a genuinely one-off bad year as easily as
   real deterioration.

6. **Close with a Sources footer** (every tool call + as-of date, plus the
   `results/red_flags_<SYMBOL>_<date>.json` path) and the exact SEBI
   disclaimer from docs/vision.md §5.

## Guardrails

- Never call Kite's order-placing/modifying tools — not applicable to this
  skill's tool set, but the rule holds project-wide (see docs/vision.md
  §5).
- Every flag traces to a tool-sourced fact via `red_flag_check.py` — never
  invent a flag from model memory or general knowledge about the company.
- A clean scan (`flag_count: 0`) is not a buy signal or an all-clear
  verdict — it means these specific checks found nothing, not that no risk
  exists. Say that plainly rather than implying more confidence than the
  scan supports.
- Surveillance-list membership (ASM/GSM) is a real regulatory fact, not a
  judgment call — always flag it if present, never soften or omit it.
