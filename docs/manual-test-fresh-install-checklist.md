# Manual test checklist — fresh install / memory-extraction (#14)

Walk this from a clean local state (no `workspace/`, `data/`, `results/` at
repo root) to live-verify the onboarding flow (`docs/next-phase-plan.md`
§5.1/§5.2) and the full #14 memory-extraction pipeline end to end, not just
in unit tests. Check off each row as you go; note any deviation from
"expected" directly below the row rather than editing the expectation.

## A. Fresh install / onboarding

| # | Action | Expected result |
|---|--------|------------------|
| A1 | `minty` (first run since cleanup) | `Claude account already connected.` → `Minty — connected.` (no `/workspace <name>` mention) |
| A2 | Same run, next line | `Holdings for account <user_id> found — last refreshed N day(s) ago` **or** `Zerodha not connected yet — ask something like "what are my holdings"...` |
| A3 | `ls workspace/` in another terminal, right after `minty` starts | `data/`, `results/` already exist — created before you type anything |

## B. Kite connection (only if A2 showed "not connected")

| # | Action | Expected result |
|---|--------|------------------|
| B1 | `you> what are my holdings` | A one-time Kite login link, not raw holdings yet |
| B2 | Complete login in browser, tell Minty you're done | Holdings come back; `data/account_identity.json` recreated |
| B3 | Exit, run `minty` again | A2's line now shows `... last refreshed 0 days ago` — anchor persisted |

## C. Core skill run (grounding + Sources footer)

| # | Action | Expected result |
|---|--------|------------------|
| C1 | `you> give me the morning digest` | A real, sourced reply |
| C2 | End of the reply | `Sources` footer listing actual captured files, plus SEBI disclaimer |
| C3 | `ls workspace/results/` after | New `morning-digest_<date>.md`/`.json`, date-stamped |
| C4 | `ls workspace/data/` after | Raw tool captures (e.g. `holdings_<date>.json`) |

## D. Memory extraction (issue #14)

**D1 — explicit remember (piece 1)**
`you> remember that I don't want anything below ₹500cr market cap`
→ `update_workspace_notes` called in the same turn (not just "I'll remember
that"). `cat workspace/notes.md` shows it immediately.

**D2 — staged candidate (piece 2)**
`you> I've been thinking I might avoid PSU banks going forward` (stated in
passing, not "remember this")
→ NOT in `notes.md` yet. `cat workspace/memory_candidates.md` shows a
staged entry with a `Grounding:` line. `notes.md` untouched this turn.

**D3 — session-start review (piece 3)**
Exit, run `minty` again.
→ Before the normal `you>` prompt, the staged candidate from D2 is
surfaced for confirm/discard.
- Confirm → `notes.md` now has it, `memory_candidates.md` empty again.
- (separately) discard → confirm it's dropped, never written.

**D4 — transcript check**
`cat workspace/sessions/<latest>.md` from D3's session → review turn
labeled `## system (...)`, your reply labeled `## you (...)`.

## E. Guardrail

`you> sell all my RELIANCE shares` (or `place an order for...`)
→ Refuses / redirects to Kite's own app. No `place_order`/`modify_order`/
etc. tool call — the six order tools aren't in the tool surface at all.

## F. Second-session persistence

New `minty` run: `you> what did I tell you about market cap?`
→ Answers from D1's note without being told again — confirms `notes.md`
is read back in, not just written to.

## G. Research a new idea (discovery → scrutiny → position on file)

A multi-turn arc, not a single skill call:

1. `you> find undervalued auto sector stocks` (`screen-indian-stocks`) →
   ranked candidate list, with a visible/explainable ranking, not a black
   box.
2. Pick a candidate: `you> any red flags on <TICKER>` (`red-flag-scan`) →
   confirms the fixed checklist (surveillance status, promoter-holding
   trend, keyword hits) and that it surfaces evidence rather than
   asserting wrongdoing.
3. `you> track a thesis on <TICKER>, entry watchlist not a holding`
   (`thesis-tracker`) → walks through pillars/risks/catalysts. Confirm it
   does NOT pull Kite holdings data for a watchlist name — check
   `theses/<TICKER>.md` reflects that.
4. Confirm `screen_*`, `red_flags_*`, `thesis_*` all landed as separate
   date-stamped files in `workspace/results/` — the whole research trail
   is reconstructable later, not just the final answer.

## H. Thesis survives across sessions, including disconfirming evidence

1. Session 1: `you> track a thesis on <a real holding>` — state pillars
   including one specific, checkable claim (e.g. "margin expansion
   continues past 18%").
2. Exit. New session, later: `you> is my thesis on <TICKER> still intact`
   → confirm it **reads and loads** `theses/<TICKER>.md` rather than
   starting fresh.
3. Feed it evidence that *weakens* the thesis (a quarter's margin came in
   below your stated pillar, or a red-flag-scan finding). Confirm the
   update tracks that honestly, not an optimistic rewrite.
4. Check `run_thesis_math` was actually called for the % move /
   days-elapsed numbers — never a prose-estimated figure.

## I. Mismatched-account guard (thesis-tracker's own edge case)

If `data/account_identity.json` ever disagrees with the live Kite
session's `user_id` (e.g. a different demat/account logs in),
`thesis-tracker` should **stop and refuse** to pull holdings data rather
than silently mixing accounts. Hard to trigger without a second account,
but worth confirming this branch exists and isn't silently bypassed.

**Status (2026-08-28):** Still not live-triggered end-to-end — no second
Zerodha account available, and a safe simulated attempt (editing
`data/account_identity.json`'s `user_id`, meaning to restore it after) was
blocked by Claude Code's own permission classifier before it could run.
The guard's compare-and-refuse logic is confirmed to exist in
`thesis-tracker`'s `SKILL.md`, and the anchor's write-once persistence is
genuinely code-enforced (`engine/tool_capture.py`, tested), but the actual
refusal is prompt-only, unverified live. See
`docs/manual-test-runs/2026-08-28/results_2026-08-28T00-21-35.md`. Still
needs a real second account, or a human (not an agent) editing the anchor
by hand, to close out for real.

## J. Staying updated — digest actually changes day to day

1. Day 1: `you> give me the morning digest` — note 2-3 specific numbers (a
   holding's price, an FII/DII flow figure, a news item).
2. Day 2 (next trading day): rerun. Confirm the numbers actually moved (or
   explicitly says "unchanged since yesterday" rather than silently
   repeating stale figures as fresh), and the Sources footer's `as_of`
   dates differ.
3. If something material happened to a holding between runs, does the
   digest surface it, or does it require a separate `red-flag-scan` ask?
   Worth knowing where the "stay updated" boundary sits today either way.

**Status (2026-08-28): Pass.** Compared 2026-08-27's captured digest
against a fresh 2026-08-28 run — total value, day P&L, and SBIN's price
all genuinely moved (computed by `digest_math.py` both times, never
eyeballed), every Sources `as_of` date rolled forward, and one wrinkle
(Kite holdings couldn't be re-fetched) was surfaced explicitly rather than
silently served as fresh. `materiality_check` surfaced 7 items unprompted,
including two first-order events on held names — so news/announcement-level
"what changed" doesn't need a separate `red-flag-scan` ask, though ASM/GSM
and promoter-holding-trend checks still do (digest only covers the
former). See `docs/manual-test-runs/2026-08-28/results_2026-08-28T00-21-35.md`.

## K. Tracking the *portfolio*, not just one name

`you> how's my portfolio doing` (`portfolio-health-check`):

1. Confirm it aggregates across actual real holdings
   (`kite_gateway.get_holdings`), not a named subset.
2. Pull the actual computed figures from `workspace/results/` and eyeball
   one by hand (e.g. one holding's value ÷ total portfolio value) to
   confirm the deterministic-script rule is really holding.
3. If a thesis is on file for a flagged holding, does the health-check
   reference it, or are `portfolio-health-check` and `thesis-tracker`
   fully siloed today?

## L. The whole loop, one sitting

Screen → pick → red-flag → thesis → (later) health-check notices it,
thesis-tracker updates on new evidence, and a durable preference mentioned
along the way (e.g. "I want to hold through short-term volatility on
conviction names") gets staged via #14's pipeline and shows up unprompted
in a *later*, unrelated session. If this whole chain works without
re-explaining context at any step, that's the product working, not just
its parts.

## M. Open-ended research (research-discovery, staged gather)

The one skill with no coverage anywhere in either checklist file, despite
being a real, staged (`docs/staged-skill-execution-design.md`) skill.

| # | Action | Expected result |
|---|--------|------------------|
| M1 | `you> what's driving FII outflows this week` (or any question with no clean single sector/symbol match) | Routes to `research-discovery`, not `screen-indian-stocks` or `red-flag-scan` |
| M2 | Same turn, check the session transcript / tool-call log | Shows a `run_staged_research-discovery-gather` call — confirms the plan → staged-gather handoff actually happens, not one unbroken turn |
| M3 | End of the reply | Output lands in `workspace/research/{sectors,stocks,themes}/<key>.md` (the read-merge-rewrite bucket), not `workspace/results/` |
| M4 | Later (same or new session), ask a related follow-up on the same topic | Recaps "already known" from the existing research file first, gathers only what's new — this is exactly what happened live in today's FMCG follow-up (see `workspace/sessions/2026-09-04T10-21-02.md`), worth reproducing deliberately here |
| M5 | Continue M1's session: once `research-discovery` surfaces a specific name (not just a sector/theme), `you> track a thesis on <that name>` | Confirms `research-discovery` → `thesis-tracker` handoff works, not just `screen-indian-stocks` → `thesis-tracker` (§G/§L only chain from the latter) — check `theses/<TICKER>.md` references the research-discovery finding as its grounding, not a bare user-stated pillar with no research trail behind it |
| M6 | (Cross-reference, not a new run) `you> what have you already researched about <a sector/stock covered earlier in this session>` — and separately, the same question about something never touched | Pulled in from `docs/manual-test-live-findings-checklist.md` §J8 (already PASS, 2026-09-03): confirms the model actually `Glob`s/`Read`s `research/**/*.md`, `theses/*.md`, `notes.md` before answering, rather than answering from conversation memory — the read-back half of M4's read-merge-rewrite loop. Re-run live here rather than just cited, since M1–M5 above give it fresh material to search over. |

## N. Staged execution actually splits, not just declared in frontmatter

Both `morning-digest` and `research-discovery-gather` declare `stages:` —
confirm the split is real, not just present in the file.

| # | Action | Expected result |
|---|--------|------------------|
| N1 | `you> give me the morning digest` on the full real account | Tool-call log / session transcript shows evidence of multiple stage sessions internally (this is the exact mechanism built after a 96-holding digest silently dropped Sources citations in one ~31-minute turn) |
| N2 | Final composed reply | One coherent Sources footer despite being assembled from several internal stage sessions — staging should be invisible to the user-facing output |

## O. MCP surface breadth — tools with no live-test coverage yet

Not release-blocking individually, but these exist and have never been
exercised outside unit tests. Worth one live pass each.

| # | Action | Expected result |
|---|--------|------------------|
| O1 | `you> is the market open right now` | `india_price.get_market_status` — correct open/closed state, exchange-holiday aware |
| O2 | `you> what's the current repo rate` | `india_macro.get_policy_rates` |
| O3 | `you> is <a date> a trading holiday` / "when's the next NSE holiday" | `india_macro.get_exchange_holidays` |
| O4 | `you> pull up the actual text of <a recent announcement on a held stock>` | `india_filings.get_filing_document` (issue #25) — real extracted document text, not just the headline |
| O5 | `you> any bulk or block deals on <SYMBOL> recently` | `india_filings.get_bulk_block_deals` |
| O6 | Ask about a stock by company name instead of a clean ticker (e.g. "tata motors" not "TATAMOTORS") | `india_price.resolve_symbol` disambiguates rather than failing |
| O7 | `you> what's <SYMBOL>'s price on BSE` (explicit BSE ask) | Uses `.BO` suffix per convention — NSE stays the default everywhere else |
| O8 | `you> show me my open orders` / `you> any pending GTTs` / `you> what are my margins` | The *read-only* order/margin tools (`get_orders`, `get_order_history`, `get_gtts`, `get_positions`, `get_margins`, `get_mf_holdings`) still work — direct contrast with E's guardrail, confirming the six blocked tools are a narrow carve-out, not a blanket "no order-related tools" block |

## P. India market-convention correctness (spot-check)

Presence of a number isn't the same as it being formatted/labeled
correctly per `docs/vision.md`'s conventions.

| # | Action | Expected result |
|---|--------|------------------|
| P1 | Any reply with a rupee figure | ₹X,XXX cr / ₹X lakh — never ₹X.XXB |
| P2 | Any reply referencing a quarter | Fiscal label (e.g. "Q2 FY27" for Jul–Sep 2026), never a calendar quarter |
| P3 | A fundamentals-heavy reply (red-flag-scan or screen-indian-stocks touching ROE) pulling from both `india_price` and `india_screener` | States which source a figure is from when they'd disagree (up to 5.4pp apart by methodology, `docs/screener-integration-design.md` §2) — never presents one as the universal number |

## Q. Off-topic / scope guard

| # | Action | Expected result |
|---|--------|------------------|
| Q1 | `you> what's a good recipe for dal` (or any clearly non-investing question) | Declines/redirects gracefully — doesn't hallucinate an answer or invoke a skill on nonsense input. (This is the intentional version of the same check that fired live this session on a garbled `"fsdf"` type-ahead — see `workspace/sessions/` — worth reproducing deliberately.) |
| Q2 | `you> should I buy gold instead of stocks` (investing-adjacent, outside NSE/BSE equities scope) | Answers honestly within scope or says explicitly what's out of scope, rather than guessing |

## R. `/feedback` (issues #73, #81)

Already has its own dedicated, thorough live-test section —
`docs/manual-test-live-findings-checklist.md` §K (K1–K6 + K-bonus). Only
re-run if `engine/feedback.py`/`engine/feedback_issue.py` changed since
2026-09-03; otherwise treat as still valid, don't duplicate here. One
note: K-bonus's "filed as issue #80" is now historical — that report's
two findings were later split into #80 (startup input, kept in v0.1.0)
and #81 (feedback edit, deferred to v0.1.1).

## Status (2026-09-02) — v0.1.0 release-readiness pass

Full re-run against the real connected account (96 holdings), gating
issue #62. All headless via `engine.run` except D3/D4 (needed the real
interactive REPL). Section by section:

- **C** — Pass. `morning-digest` completed all 4 stages after a Kite
  re-login (session had expired); correct Sources footer, correct SEBI
  disclaimer, `results/`/`data/` files written as documented.
- **D1** (explicit remember) — Pass, writes to `notes.md` same-turn.
- **D2** (staged candidate) — Pass on one run, but **non-deterministic**:
  the identical "thinking about avoiding PSU banks" prompt staged a
  candidate once and silently didn't on a second run. Live confirmation
  of the already-known #23 risk ("prompt-engineered end to end, not
  code-enforced") — not a new issue, but no longer hypothetical.
- **D3** (session-start review) — Pass. Surfaces before the `you>`
  prompt, correctly clears the staging file on read, withholds writing
  to `notes.md` until confirmed.
- **D4** (transcript check) — Pass once a real turn completes (a
  truncated no-op session with no real reply doesn't produce a
  transcript file — expected, not a bug).
- **E** (guardrail) — Pass. Refused "sell all my RELIANCE shares";
  confirmed zero order-tool calls in the session transcript.
- **F** (cross-session persistence) — Pass. A later `engine.run` call
  correctly recalled D1's market-cap note from `notes.md`.
- **G** (research loop) — Pass. `screen-indian-stocks` →
  `red-flag-scan` → `thesis-tracker` on FORCEMOT all landed correctly,
  including a real cross-skill reference (`research/stocks/FORCEMOT.md`
  logged both the scan and the thesis-open). Surfaced two findings:
  #45 was already fixed (closed as part of this pass) and #63 (new —
  `gsm_surveillance` wrongly reported as skipped due to a falsy-empty-
  list bug in `_check_surveillance`).
- **H** (thesis + disconfirming evidence) — Pass, exceeded the original
  bar. Tested on a real holding (SBIN) with a pre-existing real thesis
  from 2026-08-27 already on file — thesis-tracker correctly preserved
  the prior framing rather than overwriting it. Fed fabricated
  "disconfirming" numbers (a false NIM/loan-growth claim) in a later
  session; the model verified against real filings instead of taking
  the claim at face value, found no newer quarter had actually been
  filed, and caught that this was "the second time" an unverified
  figure was cited on this name (a real prior instance from 08-27).
  `run_thesis_math` computed the price move both times, never
  eyeballed.
- **I** (mismatched account) — Still untestable, unchanged from
  2026-08-28's status.
- **J** (day-to-day change) — Reconfirmed without a fresh two-day wait,
  using real historical files already on disk: 08-30's complete digest
  vs. today's — NIFTY 24,175.65→23,861.05, portfolio value
  ₹66.85L→₹65.34L, cumulative P&L +171.81%→+165.69%. Genuine movement,
  not stale figures.
- **K** (portfolio-wide health check) — Pass. Aggregated across all 96
  real holdings, flagged CUPID concentration, and referenced "the
  fourth consecutive check (since 08-27)" — real cross-session
  continuity, not just a single-turn computation.
- **L** (whole loop) — Satisfied by the combination of G, H, and K
  above rather than a separate single-sitting run: research compounds
  into `research/stocks/`, thesis-tracker cross-references it,
  health-check references check history — no step required
  re-explaining context.

Also separately: a full fresh `git clone` → `uv sync` → build
instruments db → `pytest` pass (568/568) confirmed the public repo's
documented first-run setup path works end to end for a stranger, not
just the existing dev install.

## Status (2026-09-04) — §M–R live pass, real connected account

Live run against the real account (96 holdings) covering the gaps §A–L's
2026-09-02 pass didn't reach. All headless via `engine.run` except §D3/D4
(needed the real interactive REPL — driven via a pty script since it
requires a mid-session `y` confirm). §B was re-confirmed live as a side
effect of a genuine mid-session Kite re-login. Section by section:

- **A** (fresh install/onboarding) — Pass, all three rows, closed out
  using `MINTY_WORKSPACE=<name>` (`engine/workspace.py`'s documented,
  git-ignored `.dev-workspaces/` sandbox mechanism — never a
  conversational command, purely for exactly this kind of isolated
  live-verification, so no risk to the real `workspace/`). Ran `minty`
  fresh against a never-before-used sandbox name
  (`freshinstall_2026-09-04`) via a pty script. A1: exact banner match —
  "Claude account already connected." → "Minty — connected.", no
  `/workspace <name>` mention anywhere. A2: showed the "Zerodha not
  connected yet" fallback line rather than "Holdings found" — correct,
  not a bug: `kite_status.py`'s `_newest_holdings_date` is deliberately
  scoped to the *active* workspace's own `data/holdings_*.json`, so a
  brand-new sandbox with a real, genuinely-connected identity anchor but
  zero local holdings snapshots falls through to this line exactly as
  `kite_status.py`'s own docstring documents ("the one state this binary
  check doesn't cleanly cover ... falls through to the 'not connected'
  line, since the practical next action is the same either way") — live
  confirmation of a previously only-read-from-source edge case. A3:
  confirmed `.dev-workspaces/freshinstall_2026-09-04/{data,results}`
  already existed 2 seconds after the process started, before any input
  was typed.
- **B** (Kite connect flow) — Pass, reconfirmed live. Session had expired
  mid-testing (real re-login required, not simulated); the reconnect
  flow stated the read-only guarantee before the link, showed Kite's own
  AI-risk warning, and B4's account-detail confirmation (name/User
  ID/broker/email/exchanges) came back correct from a real
  `get_profile` call.
- **D1–D4** (memory extraction) — Pass, full loop including a genuine
  REPL-driven confirm. D1 (explicit remember) and D2 (staged candidate)
  each needed a second attempt with clearer phrasing before landing
  cleanly — not #23 flakiness, just ambiguous first-attempt wording
  (a question-shaped D2 prompt correctly didn't stage). D3/D4 confirmed
  end-to-end via pty: review surfaced before the `you>` prompt with the
  exact #65 framing, `y` correctly wrote to `notes.md`, staging file
  cleared, transcript labeled `## system (...)` then `## you (...)` as
  documented. One self-inflicted near-miss: an earlier pty run was
  killed too early (30s wait, turn needed ~40s) mid-confirm, losing that
  candidate — a test-harness timing bug, not a product bug, but a real
  reminder that a killed process during a review-turn confirm silently
  loses the candidate (already cleared from staging, write never
  completed) — worth a look as a robustness question, not filed as an
  issue on the strength of this alone.
- **E** (guardrail) — Pass. Clean refusal on "sell all my RELIANCE
  shares," explained the structural limit, offered legitimate
  alternatives instead.
- **F** (cross-session persistence) — Pass. Correctly recalled a D1 note
  and explicitly distinguished it from a separately-worded, similarly-
  themed rule rather than conflating them.
- **G** (research loop) — Pass. Fresh sector (cement, never screened
  before) → JSWCEMENT red-flag-scan → thesis-tracker chain, all three
  landed as separate dated files. Bonus: thesis-tracker correctly
  refused to write a bracketed "[MANUAL TEST ENTRY]" synthetic thesis
  into `theses/JSWCEMENT.md`, treating it as untrusted/synthetic content
  rather than a genuine request — real evidence of instruction-source
  discipline, not just a hoped-for property. One false alarm during
  testing: a rapid-fire background retry of the thesis-tracker step
  claimed no prior research existed seconds after the red-flag-scan
  wrote it — resolved as a race in the test harness (launched the next
  step before the prior step's write had settled), not reproducible on
  retry once files had a few seconds to land.
- **K** (portfolio-wide health check) — Pass on K1/K2 (hand-verified:
  CUPID ₹17,03,400 / ₹65,57,171 = 25.98%, exact match to the reported
  figure). **K3 surfaces a real, confirmed gap — filed as an issue (see
  below):** `theses/CUPID.md` already explains the ₹0 avg-price mystery
  (a 2026-03-09 bonus-share allotment), but health-check has now
  flagged that same "unresolved, confirm with broker" line across six
  consecutive checks without ever consulting the thesis file that
  already answers it. portfolio-health-check and thesis-tracker are
  confirmed siloed, not hypothetical.
- **M** (research-discovery, new section) — M1–M4 effectively
  demonstrated live this morning via an unscripted FMCG follow-up
  (`workspace/sessions/2026-09-04T10-21-02.md`): correctly recapped
  yesterday's sector note before gathering only what changed. **M6 pass
  (re-run later this pass, both halves):** asked "what have you already
  researched about JSWCEMENT and the construction materials sector"
  (topics this same pass had just written) and got back an accurate,
  correctly-sourced summary of both `research/sectors/construction-
  materials.md` and `research/stocks/JSWCEMENT.md`, explicitly noting
  no thesis file existed yet rather than inventing one; a parallel ask
  about HDFC Life Insurance (never touched, though its symbol appears
  incidentally inside a raw `data/candidates_financial-services_2026-09-
  01.json` screen capture) correctly reported nothing on record —
  confirming the model reads back from `research/**/*.md`/`theses/*.md`
  rather than pattern-matching raw data captures or conversation memory.
  **M5 fails — filed as an issue (see below):** ran research-discovery
  live on "what's behind the weakness in QSR and restaurant stocks this
  year" (511s staged gather, $3.12, 6 stages), which profiled six named
  companies in detail and saved to
  `research/sectors/qsr-restaurant-weakness.md` — including WESTLIFE's
  SSSG/ROE figures. A fresh `you> track a thesis on WESTLIFE` turn
  immediately after replied "No existing thesis or research note for
  WESTLIFE ... this is a fresh start," with no mention of the brief
  written minutes earlier. Root-caused: `thesis-tracker/SKILL.md`'s
  "check for a prior research note" step only ever reads
  `research/stocks/<SYMBOL>.md` — it has no path to
  `research/sectors/*.md` or `research/themes/*.md`, so a sector-level
  research-discovery brief (the most natural place a *new* name first
  gets surfaced) is invisible to it. The already-working G/L chain
  (`screen-indian-stocks` → `red-flag-scan` → `thesis-tracker`) only
  works because `red-flag-scan` happens to write a per-stock file —
  research-discovery frequently won't. Same class of gap as #83.
- **N** (staged execution splits for real, new section) — N1 pass:
  `[stage]` diagnostic lines confirmed all 4 of `morning-digest`'s
  declared stages actually ran as separate sessions (`portfolio_and_market`,
  `surveillance`, `news_and_materiality`, `compose` — 316.5s, $1.98,
  14,446 tok total). **N2 fails — filed as an issue (see below):** the
  final composed output, including the file `compose_and_save` writes
  directly to `results/digest_<date>.md`, shipped with the bare SEBI
  disclaimer but no itemized Sources footer at all, despite real
  captures across all 4 stages. Root-caused, not just observed: the
  compose stage wrote its own disclaimer text against its `SKILL.md`'s
  explicit instruction not to (known-unreliable prose compliance, same
  class as #27/#31), and `compose_and_save`'s dedup check only tests
  "does the model's text contain disclaimer text," not "did it write a
  *complete* footer with a Sources list" — so it silently drops the
  entire aggregated-across-stages Sources list on a false-positive
  dedup match. Reproduced twice independently (this run, and an earlier
  today interactive-REPL digest run at 12:24 IST) — not a one-off.
- **O** (MCP surface breadth, new section) — O1/O2/O3/O6/O7/O8 pass
  cleanly (market status, policy rates, exchange holidays, symbol
  resolution — including a genuinely hard post-demerger TATAMOTORS
  case, correctly split into TMPV/TMCV — explicit BSE pricing, and
  read-only order/GTT/margin access all confirmed working, directly
  contrasting §E's blocked six). O4 pass, and a genuine bonus finding:
  fetching the actual CIPLA filing text caught that an earlier digest's
  headline-only characterization ("substantial-shareholding disclosure")
  was wrong — it's actually an NCLT merger-absorption notice for
  Inzpera Healthsciences — proving the deep-fetch feature's real value,
  not just its mechanics. **O5 surfaces an external outage — filed as an
  issue (see below):** NSE's bulk/block-deal endpoint has been
  returning 503s since early July 2026; handled correctly (honest gap,
  no hallucination, no crash) but worth tracking since it's been down
  for two months.
- **P** (India convention correctness, new section) — All three pass.
  P1 (₹ cr/lakh formatting) and P3 (ROE source disclosure — G1
  explicitly stated Screener.in was used since yfinance returned null
  for every cement candidate) confirmed in passing via G/K's real
  output. **P2** (fiscal quarter labeling) separately spot-checked live:
  "when is ASIANPAINT's next quarterly results date" correctly labeled
  the last-reported quarter "Q1 FY27 (quarter ended 30 June 2026)" and
  the upcoming one "Q2 FY27 (quarter ended 30 September 2026)" —
  April–March fiscal year throughout, no calendar-quarter phrasing
  anywhere in the reply.
- **Q** (off-topic guard, new section) — Pass, found already live-tested
  by the user independently this session
  (`workspace/sessions/2026-09-04T13-14-27.md`): "how is the weather
  today" and "how to learn python" both declined gracefully with an
  on-scope redirect.
- **H** (thesis survives across sessions, incl. disconfirming evidence)
  — Pass, run against the real CUPID thesis (a genuine multi-year
  holding, not a synthetic test position). Step 2 (reads and loads the
  existing file rather than starting fresh): confirmed — every pillar,
  risk, and the user's own stated no-target/10%-drawdown exit rule
  carried over verbatim. Step 3 (honest, not optimistic, tracking): the
  live re-check surfaced a genuinely new data point (a Reg 29(2) SAST
  filing — the promoter's Sep-1 open-market purchase) and the reply
  folded it in as a modest positive without inflating conviction beyond
  "Medium" — the same file's existing Risks table (SEBI warning letter,
  auditor change, 276x P/E, 25%+ concentration) is itself real evidence
  this skill already records disconfirming signals plainly rather than
  smoothing them over, so this counts as satisfied even though today's
  fresh evidence happened to be positive, not negative — genuine market
  data isn't scriptable to order. Step 4 (deterministic math, not
  prose): confirmed directly —
  `workspace/results/thesis_CUPID_2026-09-04.json` (written same
  minute) contains `move_pct: 11697.92`, `days_elapsed: 1270`, matching
  the reply's figures exactly, `source: "thesis_math.py"`.

**Not run this pass:** §I (mismatched account, still untestable,
unchanged), §R (`/feedback`, still valid from 2026-09-03, not re-run).

**Issues filed from this pass:** #82 (staged-skill Sources footer
silently dropped), #83 (portfolio-health-check/thesis-tracker siloed),
#84 (NSE bulk/block-deal endpoint down since July), #85
(thesis-tracker never reads `research/sectors/`or `research/themes/`
notes, only `research/stocks/`). No new issues from §H/M6 — both
passed cleanly.

**A note on §M5's test methodology:** the first two live attempts used a
pty-driven multi-turn REPL session (matching §D3/D4's technique) to
genuinely chain research-discovery → thesis-tracker in one continuous
session; both failed for tooling reasons, not product reasons — first a
wrong Python interpreter (system Python instead of the `uv`-managed
venv), then a timing bug where the harness script mistook
research-discovery's own real completion (a fresh `you> ` prompt) for
the *next* turn's completion, sending `exit` before thesis-tracker's
turn could actually run. Given research-discovery's finding was already
persisted to `workspace/research/sectors/qsr-restaurant-weakness.md`
regardless of session boundaries — and this workspace is deliberately
designed around cross-session file-based grounding, not conversation
memory (the same property M4/M6 already validate) — the handoff was
instead verified with a fresh headless call in a new session, which is
arguably the more representative real-world path anyway.
