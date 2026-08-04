---
name: morning-digest
description: Use when the user asks for today's portfolio/market digest or brief — e.g. "give me the morning digest", "what happened overnight", "how's my portfolio today". A scheduled OS reminder may prompt the user to ask for this each morning (see docs/vision.md §2), but there is no separate unattended pipeline — every digest is this same interactive skill, run on demand. Not for a deep portfolio review (use portfolio-health-check) or single-stock thesis work — this is a short, repeatable daily snapshot, not an analysis session.
expected_outputs:
  - "workspaces/{workspace}/results/digest_{date}.json"
  - "workspaces/{workspace}/results/digest_{date}.md"
deterministic_scripts:
  - id: digest_math
    path: scripts/digest_math.py
    args:
      - {name: holdings_file, kind: positional, required: true, description: "Path (relative to the workspace) to the saved holdings snapshot, e.g. data/holdings_<date>.json"}
      - {name: quotes_file, kind: positional, required: false, description: "Path to the saved live-quotes snapshot, e.g. data/live_quotes_<date>.json — omit only if it couldn't be fetched"}
  - id: surveillance_check
    path: scripts/surveillance_check.py
    args:
      - {name: holdings_file, kind: positional, required: true, description: "Path to the saved holdings snapshot"}
      - {name: asm_file, kind: positional, required: true, description: "Path to the saved ASM surveillance-list envelope"}
      - {name: gsm_file, kind: positional, required: true, description: "Path to the saved GSM surveillance-list envelope"}
      - {name: date_tag, kind: positional, required: true, description: "Today's date tag, YYYY-MM-DD — used for the output filename, not derived from the input filenames"}
  - id: materiality_check
    path: scripts/materiality_check.py
    args:
      - {name: digest_file, kind: positional, required: true, description: "Path to the saved results/digest_<date>.json from the digest_math step"}
      - {name: date_tag, kind: positional, required: true, description: "The digest's date tag, YYYY-MM-DD"}
---

# Morning Digest

A ≤2-minute, portfolio-aware daily brief: index snapshot, today's portfolio
move, biggest movers, FII/DII flow, sector-aware news/announcement
materiality flags, and any surveillance red flags on held names — all
grounded in tool data, computed in code. The final chat response of this
skill run *is* the digest, so write it as the actual deliverable, not a
summary of what you did.

Workspace-scoped, same convention as every other skill (an earlier version
of this skill treated it as a standing, repo-root job — that was inherited
from the old repo's unattended `launchd` automation, which needed a fixed
path with no workspace ambiguity for a notification/script to find. This
project doesn't have that pipeline — every digest is triggered by the user,
same as any other skill — so the exception no longer has a reason to
exist).

## Steps

## Stage 1: Portfolio & market data

1. **Confirm a workspace.** This skill writes into the current workspace's
   `data/` and `results/`. If no workspace is open, ask the user to open or
   name one first (a workspace named after a recurring daily habit, e.g.
   `daily`, works fine — nothing about this skill requires a
   symbol/topic-specific name).

2. **Check market status.** Call `india_price.get_market_status`. If it's a
   weekend/holiday or pre-open, frame the brief around the last completed
   session and overnight flow rather than "today's move" — don't claim a
   live intraday move that isn't happening. (Holiday awareness comes from a
   live NSE lookup that fails open — check `holiday_calendar_loaded` in the
   result; if it's `False` the lookup degraded to a weekday-only check, so
   also sanity-check against the index quote in step 3.)

3. **Verify account identity, then fetch real holdings from Kite.** Call
   `kite_gateway.get_profile` and compare its `user_id` against the anchor
   in **root** `notes.md` (not the workspace's own `notes.md` — this is a
   durable, cross-workspace fact, not a workspace-scoped one, per
   docs/vision.md's Working Notes convention) → "Zerodha account identity".
   No anchor yet? Save this profile's identity as the anchor and proceed.
   Anchor exists and doesn't match? **Stop** — don't fetch or overwrite the
   workspace's `data/holdings_<date>.json`; report plainly that a different
   Zerodha account is connected than expected. Minty is a single-account
   tool by design, not multi-tenant — a second account's data would
   silently corrupt the cached snapshot rather than raise an error. Then
   call `kite_gateway.get_holdings` — read-only by construction, not just
   policy: the order-placing/-modifying tools (`place_order`,
   `modify_order`, `cancel_order`, GTT tools) aren't in `kite_gateway`'s
   tool surface at all (see docs/vision.md §5). The engine automatically
   saves the raw result to the workspace's `data/holdings_<YYYY-MM-DD>.json`
   as soon as the call returns — no separate save step.

   The shape is already known: each entry has `tradingsymbol`, `exchange`,
   `isin`, `quantity`, `average_price`, `last_price`, `close_price`, `pnl`
   (no sector/industry field — sector coverage is a separate, partial
   effort, see `mcp/common/instruments.py`). Read it with the `Read` tool
   if you need to inspect it, rather than ad-hoc Bash.

4. **Fetch an index snapshot.** Call
   `india_price.get_quote(["^NSEI", "^BSESN", "^NSEBANK", "^INDIAVIX"])`
   for NIFTY 50, SENSEX, BANKNIFTY, and INDIA VIX last-price/day-change. The
   engine automatically saves this to `data/index_quote_<date>.json` — it
   recognizes an index-only call by the `^`-prefixed tickers, so this stays
   separate from step 4b's holdings quotes below even though both call the
   same tool.

4b. **Fetch live prices for every held symbol.** Call
   `india_price.get_quote(symbols)` with the full list of distinct
   `tradingsymbol`s from step 3's holdings (one batched call, not a loop).
   The engine automatically saves this to `data/live_quotes_<date>.json`.
   This is what keeps today's
   per-position move accurate even when Kite's own cached
   `last_price`/`close_price`/`day_change_percentage` fields are stale —
   `india_price` needs no Kite session and is always fetched fresh in this
   step (see `scripts/digest_math.py`'s docstring for why this matters). A
   handful of symbols (G-Secs, some ETFs) won't resolve on yfinance;
   `digest_math.py` falls back to that position's own Kite-snapshot fields
   automatically and reports which symbols it fell back for.

5. **Fetch FII/DII flow.** Call `india_filings.get_fii_dii_flows` (no
   symbol arg — market-wide). The engine automatically saves this to
   `data/fii_dii_<date>.json`.

6. **Run the computation, not the model** — call the `run_digest_math`
   tool (not Bash) with `workspace_root` set to the exact active-workspace
   path, `holdings_file` set to `data/holdings_<date>.json`, and
   `quotes_file` set to `data/live_quotes_<date>.json`.

   Writes `results/digest_<date>.json` — total value/invested/P&L, today's
   portfolio P&L and %, top concentration, today's gainers/losers by %, the
   biggest ₹ contributors/detractors to today's move, and
   `stale_fallback_symbols` (any held symbol priced from the Kite snapshot
   instead of a live quote — mention these in the brief if the list is
   non-empty). Read every figure from this file, never from memory or
   eyeballing the raw holdings.

## Stage 2: Surveillance

7. **Surveillance check, bounded.** Call
   `india_filings.get_surveillance_list("ASM")` and `("GSM")` — don't call
   NSE per-symbol for this. The engine automatically saves the two raw
   results to `data/surveillance_asm_<date>.json` and
   `data/surveillance_gsm_<date>.json` as each call returns — no separate
   save step. Then call the `run_surveillance_check` tool (not Bash) with
   `workspace_root`,
   `holdings_file`/`asm_file`/`gsm_file` set to those three saved paths, and
   `date_tag` set to `<date>` — the output filename comes from this
   argument, not from parsing the input filenames, so it stays
   `surveillance_flags_<date>.json` regardless of what you named the saved
   ASM/GSM files.

   Writes `results/surveillance_flags_<date>.json` with `asm_hits`/`gsm_hits`
   — read the flags from there, never intersect the surveillance lists
   against holdings by hand (grep, a manual loop, etc.) — see
   `scripts/surveillance_check.py`'s docstring for why. If either
   `get_surveillance_list` call errors (NSE circuit open/down), pass its
   error envelope straight through as the saved file — the script treats an
   error envelope as zero hits, not a crash, so the digest still completes;
   note the outage in the brief rather than silently reporting no flags.

## Stage 3: News & materiality

8. **Announcement check, bounded to today's watch set.** The bounded set is
   `top_concentration ∪ day_gainers_by_pct ∪ day_losers_by_pct` from step 6's
   `results/digest_<date>.json` (union, deduped — up to ~20 symbols, not all
   ~100+ holdings) — a stock that swung today but isn't a top holding by
   value still gets checked. For each symbol in that set, call
   `india_filings.get_announcements(symbol, from_date, to_date)` **with
   `from_date`/`to_date` explicitly set to yesterday/today** (`DD-MM-YYYY`,
   NSE's native format — see the tool's docstring). Omitting the date range
   is a real bug, not just a nicety: NSE's default window returns years of
   history per symbol (multi-MB payloads for large-caps like TCS/SBIN) — the
   opposite of "bounded," and needlessly heavy on both NSE and context.
   Checking every holding every morning would also hot-loop NSE's endpoint
   — see docs/vision.md §5's "be polite to data sources" rule — so this is
   a deliberate, bounded subset, not full coverage; say so if the user asks
   why a smaller holding's news isn't in the brief. The engine automatically
   saves each symbol's raw result to `data/announcements_<symbol>_<date>.json`
   as each call returns — step 8b reads it from there, no separate save
   step needed.

8b. **News fetch, same bounded set.** For each symbol in step 8's bounded
    set, call `india_news.get_news(symbol, limit=5)` using the raw NSE
    tradingsymbol as the query. Known limitation, not hidden: `india_news`'s
    own docstring recommends a company name for best results; the raw
    symbol is the pragmatic choice here (avoids a second lookup step) and
    may be noisier for less-recognizable tickers. The engine automatically
    saves each result to `data/news_<symbol>_<date>.json` as each call
    returns. Cost, stated
    explicitly: up to ~20 `get_announcements` calls and up to ~20
    `india_news.get_news` calls, each throttled by their respective shared
    fetchers (≥2s between requests) → roughly a minute or more of added
    wall-clock time. Acceptable for an on-demand morning check with no tight
    time budget, but a real cost — worth watching if it ever becomes a
    problem. Then call the `run_materiality_check` tool (not Bash) with
    `workspace_root`, `digest_file` set to `results/digest_<date>.json`,
    and `date_tag` set to `<date>`.

    Writes `results/materiality_flags_<date>.json` — a ranked list of
    sector-aware materiality flags (severity, matched signal, a
    pre-written rationale, portfolio weight) covering both sources, sorted
    high-severity/high-weight first. Read the flags from there — **never
    judge materiality yourself**; the rubric in
    `mcp/common/sector_materiality.py` is the only source of "does this
    matter," same "deterministic calculation only" discipline as
    `digest_math.py`.

## Stage 4: Compose & save

9. **Compose the brief** (this is the actual output, not a report about the
   output) — target ≤2 minutes to read, per the user's own stated
   preference in root `notes.md`. Structure:
   - Index snapshot (NIFTY/SENSEX/BANKNIFTY/VIX, day change).
   - Portfolio today: total day P&L (₹ and %), then top 2-3 ₹ contributors
     and detractors — not a full position-by-position readout.
   - Overall portfolio P&L (₹ and %) — one line, not the focus.
   - FII/DII net flow for the latest session.
   - Surveillance flags on held names, if any (step 7) — omit the section
     entirely if none, don't say "no flags" for every symbol.
   - **What needs attention** (replaces a plain announcement list) — the
     ranked flags from `results/materiality_flags_<date>.json` (step 8b),
     omit entirely if `flag_count` is 0. Take the first ~8 entries **of the
     `flags` array itself, in the order the script already sorted them** —
     one bullet per array element, in array order, nothing added or
     merged. Per flag, every field in the bullet (`symbol`, sector,
     `source_type`, `matched_signal`) must be copied verbatim from that
     *same array element* — **never assemble a bullet by combining fields
     from two different flags**, and never invent or infer a flag that
     isn't a literal element of the array (e.g. don't reuse a nearby
     announcement's headline under a different symbol because it "seems
     related"). Per flag, state: symbol, canonical sector (or "sector not
     covered" + `sector_source` if `"yfinance"`/`"uncovered"`), portfolio
     weight, whether it's news or an announcement, the matched signal, and
     the script's own pre-written `rationale` (why this *category* of
     signal is sector-material — narrated as-is, never reworded into a
     prediction/valence claim). Alongside it, write a one-line **factual
     gloss of this specific item** — e.g. "Baazar Style Retail has filed a
     ₹28.18 Cr suit against the company" rather than just labeling it
     "Litigation" — but **restate only facts already present in that same
     flag's own `headline` field** (the news title or announcement text the
     script already extracted). Do not add outside knowledge, do not infer
     a cause the headline doesn't state, and do not speculate about what
     happens next — the gloss explains *what the headline says*, the
     `rationale` explains *why that category matters*; neither line is a
     predicted price impact or bullish/bearish framing. That split is the
     guardrail, not a style choice. If a bullet's signal already had its
     `rationale` spelled out earlier in the same list, "same rationale as
     above" may replace the rationale clause, but the
     symbol/sector/weight/source-type/signal fields must still come from
     that flag's own array element, not be assumed from context. When
     noting how many flags were omitted, count precisely: `flag_count`
     minus the number of bullets actually shown — recount by hand rather
     than estimating, since an inflated or wrong count reads as more
     ungrounded than saying nothing.
   - If step 6's `stale_fallback_symbols` is non-empty, note briefly which
     symbols' prices came from the (possibly stale) Kite snapshot rather
     than a live quote.

10. **Save a copy** of the composed brief to `results/digest_<date>.md` —
    the audit trail for what was actually sent, alongside the computed JSON.

11. **Do not write digest content into the workspace's notes.md.** Prices,
    day moves, and FII/DII flow are exactly the kind of ephemeral,
    date-scoped facts docs/vision.md's Working Notes convention says NOT to
    save ("prices/quotes (stale next turn)... news headlines
    (date-scoped)"). Only write to `notes.md` if something durable surfaced
    (e.g. the user states a new standing preference in reaction to the
    digest) — that's rare for this skill and should not happen by default.
    If it does, use the `update_workspace_notes` tool (not `Write`), same
    as portfolio-health-check's step 5 — it always saves to the workspace's
    `notes.md`, never a different filename.

12. **Close with a Sources footer** (tool + as-of date for every figure,
    including the computed-file path — for portfolio figures, cite both
    `data/holdings_<date>.json` (quantity/avg_price) and
    `data/live_quotes_<date>.json` (prices)); also cite
    `india_filings.get_announcements` and `india_news.get_news` (bounded
    set, date) and `results/materiality_flags_<date>.json` if the "What
    needs attention" section is present. Close with the exact SEBI
    disclaimer from docs/vision.md §5.

## Guardrails

- Never call Kite's order-placing/modifying tools — they aren't in
  `kite_gateway`'s tool surface at all; only read-only calls
  (`get_holdings`, etc.) are possible.
- Never compute P&L, day change, or weight by LLM arithmetic — always
  through `scripts/digest_math.py`. Never compute the surveillance-list
  intersection by hand either — always through `scripts/surveillance_check.py`.
  Never judge whether news/an announcement is material by hand either —
  always through `scripts/materiality_check.py` (backed by
  `mcp/common/sector_materiality.py`'s rubric); never write a
  bullish/bearish or predicted-impact claim in the "What needs attention"
  section — the script's `rationale` field is the only permitted
  explanation of *why* something matters. The per-item factual gloss (step
  9) may restate facts already present in the flag's own `headline` field,
  nothing else — no outside knowledge, no inferred cause, no "this means/
  could mean" language.
- Bound NSE calls to the surveillance lists (2 calls) plus announcement
  checks on the `top_concentration ∪ day_gainers_by_pct ∪
  day_losers_by_pct` set (≤~20 calls) plus the same-bounded `india_news`
  calls (≤~20 calls) — never loop either over the full holdings list, and
  always pass `from_date`/`to_date` to `get_announcements` (unbounded calls
  return years of history).
- Digest output is ephemeral by design — it belongs in the workspace's
  `results/`, not `notes.md`.
- If `get_market_status` reports the market closed, don't describe a
  holiday/weekend as "today's move."
