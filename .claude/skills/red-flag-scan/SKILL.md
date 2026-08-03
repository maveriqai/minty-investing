---
name: red-flag-scan
description: Use when the user wants a governance/safety-focused check on one specific held or watchlist stock — e.g. "any red flags on STOCKA", "check XYZ for governance issues before I add", "should I be worried about this holding". Not for a portfolio-wide check (use portfolio-health-check).
expected_outputs:
  - "workspaces/{workspace}/results/red_flags_*_{date}.json"
---

# Red-Flag Scan

A fixed governance/safety checklist for one NSE-listed stock: surveillance
status, promoter-holding trend, keyword hits in recent filings and news, and
balance-sheet stress thresholds. Every check runs in code
(`scripts/red_flag_check.py`), never as LLM judgment — this skill surfaces
evidence and lets the user weigh it, it never asserts wrongdoing.

## Steps

1. **Confirm a workspace.** Reads/writes the current workspace's `data/`,
   `results/`, `notes.md`. If none is open, ask which one, or offer to open
   one for this symbol.

2. **Resolve the symbol.** `india_price.resolve_symbol` if the user gave a
   company name rather than an exact NSE trading symbol.

3. **Pull the five inputs**, one call each, saving each raw response to
   `data/<kind>_<SYMBOL>_<date>.json`:
   - `india_filings.get_shareholding_pattern(symbol)`
   - `india_filings.get_surveillance_list("ASM")` — market-wide, not
     per-symbol; reuse the same-day file if another skill already pulled it
     in this session rather than re-fetching.
   - `india_filings.get_surveillance_list("GSM")` — same reuse note.
   - `india_filings.get_announcements(symbol, from_date=<6 months back>)` —
     bounded window, not the full filing history.
   - `india_news.get_news(<company name>, limit=10)`
   - `india_price.get_fundamentals(symbol)`

   Any one of these can fail or come back with a `data.error` — that's
   expected (NSE outages, thin small-cap coverage), not a reason to stop.
   Pass whatever succeeded to the next step; missing inputs just skip their
   checks.

4. **Run the deterministic scan:**

   ```
   uv run python <path-to-this-skill>/scripts/red_flag_check.py --symbol <SYMBOL> \
     --shareholding data/shareholding_<SYMBOL>_<date>.json \
     --surveillance-asm data/surveillance_asm_<date>.json \
     --surveillance-gsm data/surveillance_gsm_<date>.json \
     --announcements data/announcements_<SYMBOL>_<date>.json \
     --news data/news_<SYMBOL>_<date>.json \
     --fundamentals data/fundamentals_<SYMBOL>_<date>.json
   ```

   Omit any `--` flag whose input wasn't available — the script handles
   missing inputs by skipping that check, not by crashing. Writes
   `results/red_flags_<SYMBOL>_<date>.json` with `flags`, `flag_count`,
   `checks_performed`, `checks_skipped`.

5. **Compose the brief from the script's output, not from re-reading the
   raw tool data.** For each flag: state the category and quote the
   evidence field verbatim — don't editorialize beyond what the evidence
   says. If `checks_skipped` is non-empty, disclose which checks couldn't
   run and why (upstream error vs. missing data), rather than silently
   presenting a partial scan as complete. If `flag_count` is 0, say so
   plainly — "no flags found" is a real, useful result, not a non-answer.

   Two caveats worth stating explicitly when relevant: (a) keyword hits in
   announcements/news are *mentions*, not confirmed issues — a "related
   party" hit could just as easily be routine disclosure language; (b) the
   fundamentals leverage/liquidity thresholds are fixed heuristics
   (Debt/Equity > 2, current ratio < 1), not sector-adjusted, and yfinance's
   `debt_to_equity` field is occasionally in unexpected units for thinly
   covered small-caps — sanity-check an extreme reading rather than
   reporting it at face value.

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
