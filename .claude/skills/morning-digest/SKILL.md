---
name: morning-digest
description: Use when the user asks for today's portfolio/market digest or brief — e.g. "give me the morning digest", "what happened overnight", "what's moved in my portfolio today". A scheduled OS reminder may prompt the user to ask for this each morning (see docs/vision.md §2), but there is no separate unattended pipeline — every digest is this same interactive skill, run on demand. Not for a general portfolio-status check or single-stock thesis work — phrases like "how's my portfolio doing" or "am I too concentrated in anything" belong to portfolio-health-check, not here. This is a short, repeatable daily market-moved snapshot, not a structured P&L/concentration/winners-losers review.
expected_outputs:
  - "{workspace}/results/digest_{date}.json"
  - "{workspace}/results/digest_{date}.md"
tool_call_budgets:
  # Audit-only per-turn count (engine/tool_budget.py) — not enforced, just
  # flagged to the engine's own console if exceeded. Set a bit above step
  # 8's ~20-symbol bounded set.
  india_news.get_news: 25
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
# Staged execution (docs/staged-skill-execution-design.md) — splits this
# skill's run into four fresh sessions instead of one long turn, to keep
# any single turn's context bounded. Each stage's prompt is this file's
# own body (below) plus that stage's own `instructions`; `needs`/`produces`
# reuse the same glob-pattern shape as `expected_outputs` above. The
# `compose` stage declares no `produces` — its output is written by the
# engine itself (engine/staged_skills.py's `compose_and_save`), not by a
# deterministic script inside that stage's own session, so there's nothing
# on disk to mechanically check right when that stage's session closes.
stages:
  - id: portfolio_and_market
    instructions: |
      This is Stage 1 (Portfolio & market data) of this run — steps 1-6 in
      the Steps section above. Confirm the workspace, check market status,
      verify account identity and fetch holdings, fetch the index snapshot
      and live quotes for every held symbol, fetch FII/DII flow, then call
      run_digest_math. Stop once this stage's steps are done — surveillance,
      news, and composing the brief are separate stages, not part of this
      one.
    produces:
      - "{workspace}/results/digest_{date}.json"
  - id: surveillance
    instructions: |
      This is Stage 2 (Surveillance) of this run — step 7 in the Steps
      section above. Read results/digest_{date}.json (see the file list
      below) for today's full held-symbol set (`all_positions`), fetch the
      ASM/GSM surveillance lists filtered to those symbols, and call
      run_surveillance_check. Stop once this stage's step is done.
    needs:
      - "{workspace}/results/digest_{date}.json"
    produces:
      - "{workspace}/results/surveillance_flags_{date}.json"
  - id: news_and_materiality
    instructions: |
      This is Stage 3 (News & materiality) of this run — steps 8-8b in the
      Steps section above. Read results/digest_{date}.json (see the file
      list below) for today's bounded symbol set, then for each symbol in
      that set call get_announcements once and get_news once (symbol only,
      never also by company name), then call run_materiality_check. Stop
      once this stage's steps are done.
    needs:
      - "{workspace}/results/digest_{date}.json"
    produces:
      - "{workspace}/results/materiality_flags_{date}.json"
  - id: compose
    instructions: |
      This is Stage 4 (Compose & save) of this run — steps 9 and 12 in the
      Steps section above (step 10's save and step 12's Sources footer
      happen automatically after this stage — write the brief itself, nothing
      else). Read the result files listed below and compose the morning
      digest brief per step 9's structure. Any file listed below as missing
      means that stage failed — say so explicitly in the relevant section
      instead of omitting it or guessing at its contents.
    needs:
      - "{workspace}/results/digest_{date}.json"
      - "{workspace}/results/surveillance_flags_{date}.json"
      - "{workspace}/results/materiality_flags_{date}.json"
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

0. **Before triggering the staged run, confirm Kite is reachable.** Call
   `kite_gateway.get_profile` once, in this top-level turn. If there's no
   active session, present the `login` tool's returned URL, ask whether to
   refresh, and **stop this turn there** — don't call
   `run_staged_morning-digest` yet. A stage can't pause mid-run to ask you
   anything (`run_staged_morning-digest` is one atomic call with no
   back-and-forth once started, see docs/staged-skill-execution-design.md
   §8), so this has to be a genuinely separate turn, not a question you ask
   and then answer yourself by continuing anyway. Once the user replies —
   confirming login, or saying to proceed anyway — call
   `run_staged_morning-digest`: if they declined, step 3 below falls back
   to the workspace's existing cached holdings rather than skipping the
   digest.

## Stage 1: Portfolio & market data

1. **The workspace is already open.** The engine hands you the one active
   workspace's path before you ever see this turn (the "Active workspace:"
   note above) — there's no naming step, and no case where none is open.
   Write into its `data/` and `results/` as documented below.

2. **Check market status.** Call `india_price.get_market_status`. If it's a
   weekend/holiday or pre-open, frame the brief around the last completed
   session and overnight flow rather than "today's move" — don't claim a
   live intraday move that isn't happening. (Holiday awareness comes from a
   live NSE lookup that fails open — check `holiday_calendar_loaded` in the
   result; if it's `False` the lookup degraded to a weekday-only check, so
   also sanity-check against the index quote in step 3.)

3. **Verify account identity, then fetch real holdings from Kite.** Read
   `data/account_identity.json` at the **repo root** first, if it exists
   (not inside the workspace — this is an install-wide anchor, not
   workspace content). Then call `kite_gateway.get_profile` and compare
   its `user_id` against whatever you just read.
   - **No anchor file yet:** the engine writes one automatically, the
     moment this call succeeds — nothing for you to do. Just proceed.
   - **Anchor existed and matches:** proceed.
   - **Anchor existed and doesn't match:** **Stop** — don't fetch or
     overwrite the workspace's `data/holdings_<date>.json`; report plainly
     that a different Zerodha account is connected than expected. Minty is
     a single-account tool by design, not multi-tenant — a second
     account's data would silently corrupt the cached snapshot rather than
     raise an error. There's no tool call that can update the anchor —
     it's engine-managed and write-once (see `engine/tool_capture.py`) —
     so this stays flagged on every run until a human resolves it by hand
     (deleting `data/account_identity.json`), not something you can fix
     from inside a conversation.

   Then call `kite_gateway.get_holdings` — read-only by construction, not just
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

   **No active Kite session** (`get_profile`/`get_holdings` fails that
   way, not a real error): don't stop the stage over it — this session has
   no memory of whether step 0 already asked about it, so just fall back.
   Glob the workspace's `data/` for the newest existing `holdings_*.json`
   and use that instead of a fresh fetch; skip the identity check (nothing
   new to compare). Pass that file straight to step 6's `run_digest_math`
   as `holdings_file` — its `quotes_file` argument still gets today's live
   prices from step 4b, so the output keeps today's date and today's
   pricing even though the position sizes are however old that snapshot
   is (`digest_math.py` derives the output date from `quotes_file`, not
   `holdings_file`, for exactly this reason). No cached snapshot exists at
   all (fresh workspace, never a successful fetch)? Then there's genuinely
   nothing to fall back to — say so plainly rather than guessing.

   **This fallback is only for a real "no session" failure — never apply
   it to an account-mismatch denial.** The engine also enforces the
   identity check above itself (issue #19): if `get_holdings` is denied
   with a message about a different Zerodha account being connected,
   that's not "no active session" and this fallback does not apply. Treat
   it exactly like the "Anchor existed and doesn't match" branch above —
   stop, report the mismatch plainly, don't fetch or fall back to any
   cached holdings file.

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

7. **Surveillance check, bounded.** Read `results/digest_<date>.json`
   (produced by Stage 1) and collect every symbol from its
   `all_positions` field — that's today's actual held-symbol set,
   whichever holdings snapshot Stage 1 ended up using (today's or a
   fallback). Call `india_filings.get_surveillance_list("ASM",
   symbols=<that list>)` and `("GSM", symbols=<that list>)` — always pass
   `symbols`, never omit it. The unfiltered market-wide list runs into
   tens of thousands of characters and can silently exceed the model's own
   tool-result size cap, which substitutes a plain-text redirect in place
   of the real data instead of a real error (issue #24, hit live twice:
   2026-08-27 and again 2026-08-28) — filtering to your own held symbols
   keeps the response small and avoids that failure mode almost entirely.
   The engine automatically saves the two raw results to
   `data/surveillance_asm_<date>.json` and `data/surveillance_gsm_<date>.json`
   as each call returns — no separate save step. Then call the
   `run_surveillance_check` tool (not Bash) with `workspace_root`,
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

   **If a saved ASM/GSM file still looks corrupted, incomplete, or
   otherwise unreadable — even after filtering — never hand-author or
   patch it with `Write`.** `workspace/data/` exists to hold verbatim,
   engine-captured tool output and nothing else; a `Write` call there
   produces content nobody actually fetched, indistinguishable later from
   a real capture, which is a worse version of the exact grounding failure
   issue #24 is about (found live 2026-08-28: a prior run of this same
   step, faced with a corrupted capture, read fragments of the SDK's own
   raw overflow file and used `Write` to reconstruct a "partial" surveillance
   list with an unverifiable completeness claim). Treat it the same as any
   other failed fetch: report the gap honestly in the brief (which symbols'
   surveillance status couldn't be confirmed this run) and let
   `run_surveillance_check` work with whatever real data exists, same as
   the NSE-outage case above.

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
    tradingsymbol as the query — **once per symbol, not also by company
    name** (verified live: the two return identical results here; the
    second call is pure overhead). The engine automatically saves each
    result to `data/news_<symbol>_<date>.json` as each call returns. Cost,
    stated explicitly: up to ~20 `get_announcements` calls and up to ~20
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
   preference in `notes.md`'s `## Preferences` section. Structure:
   - Index snapshot (NIFTY/SENSEX/BANKNIFTY/VIX, day change).
   - Portfolio today: total day P&L (₹ and %), then top 2-3 ₹ contributors
     and detractors — not a full position-by-position readout. If step 3
     fell back to a cached holdings snapshot, `results/digest_<date>.json`'s
     `input_file` won't match today's date — say plainly that position
     sizes are as of that older date (prices/index/news are still today's).
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

10. **A copy of the composed brief is saved automatically** — once
    `results/digest_<date>.json` exists (step 6) and this turn's reply
    text is complete, the engine writes it verbatim to
    `results/digest_<date>.md`, including the Sources footer (step 12).
    No separate save step; nothing to do here beyond composing the brief
    itself well.

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
  calls, one per symbol (≤~20 calls, audited by the engine — see step 8b) —
  never loop either over the full holdings list, and always pass
  `from_date`/`to_date` to `get_announcements` (unbounded calls return
  years of history).
- Digest output is ephemeral by design — it belongs in the workspace's
  `results/`, not `notes.md`.
- If `get_market_status` reports the market closed, don't describe a
  holiday/weekend as "today's move."
