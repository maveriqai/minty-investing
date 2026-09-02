# Manual test checklist — 2026-08-28 live-testing findings

Derived from a real, unscripted install/onboarding/features test done
directly in a terminal (not synthetic scenarios) — every row below traces
to an actual observed transcript, either as an issue filed that session
(#34-#46) or a behavior confirmed to already work correctly. Two issues
(#43, #46) were fixed same-day (commit `5ff0af8`) and need live
re-verification here, not just the unit tests already covering them; the
rest are open and this checklist exists to keep their repro steps
reachable rather than only living in prose inside each issue.

Run from the real connected account, not a synthetic one — several rows
(E, G) specifically depend on this account's actual shape (96 holdings)
to reproduce or verify at all. Check off each row as you go; note any
deviation directly below the row rather than editing the expectation.

## A. Fresh install / global entrypoint (#34)

| # | Action | Expected result |
|---|--------|------------------|
| A1 | `git clone` into a second scratch folder, `uv sync` there while the main dev repo (`~/minty-investing`) is untouched | A second package-resolution step silently uninstalls `minty-investing==0.1.0` (pointing at the dev repo) and reinstalls it from the scratch clone — the global `minty` entrypoint now points at the scratch folder, no warning printed. **Known gap, not yet fixed** — confirm still reproduces this way. |
| A2 | After A1, run `minty` from the dev repo directory | Still launches the scratch clone's installed version, not the dev repo's — confirms the entrypoint, not the cwd, decides which code runs |
| A3 | `cd ~/minty-investing && uv sync` (repoint back) | Global entrypoint now points at the dev repo again — confirm this is the only fix, i.e. still a manual, undocumented step |

## B. Zerodha connect flow (regression baseline — worked well)

| # | Action | Expected result |
|---|--------|------------------|
| B1 | Fresh install, `you> where are my holdings` (no explicit "connect") | Model proactively offers to connect, not a bare error |
| B2 | `you> connect my zerodha account` | States the read-only guarantee inline *before* showing the link (not buried in docs) |
| B3 | Same turn | Kite's own "AI systems are unpredictable" warning + login link shown |
| B4 | Complete login, tell Minty "done" | Confirms with real account details (name, User ID, broker, email, exchanges) pulled from `get_profile`, not guessed |
| B5 | End of that reply | Exactly one Sources line + one disclaimer — no duplication (#27/#28 regression check) |

## C. Turn-level activity feedback (#35, #42)

| # | Action | Expected result |
|---|--------|------------------|
| C1 | Send a message that triggers a long multi-tool-call turn (e.g. a sector screen — see D1) and watch the terminal from the moment you hit enter | **Currently**: terminal stays completely silent until the first output chunk arrives — no spinner/indicator during the ~tens of tool calls. #35, not yet fixed. |
| C2 | During that same silent span, type a short next message ahead of time (don't press enter until output starts appearing) | **Currently**: the typed-ahead text visually garbles/interleaves with the terminal redraw once output starts streaming (e.g. words split mid-way with extra spaces) — root-caused as C1's silence, not a capture artifact. #42, not yet fixed, explicitly linked to #35. |

## D. Multi-candidate skill output structure (#36, #37, #38, #39)

| # | Action | Expected result |
|---|--------|------------------|
| D1 | `you> research investment opportunities in the automotive sector` (or any query that fans out to screen-indian-stocks → red-flag-scan on the top candidates) | Numbers correctly sourced/dated; both ROE methodologies (yfinance vs Screener.in) disclosed and reconciled rather than presented as one figure; a scary-looking keyword (e.g. "insolvency") correctly contextualized rather than left as a bare flag |
| D2 | Same reply, scroll to the Sources footer | **Currently**: ~70 lines, one per candidate per data source (e.g. 25 candidates × 2 fundamentals sources) — technically grounded but functionally an unreadable wall. #36, not yet fixed. |
| D3 | Same reply, look for engine diagnostic lines mixed into the model's own text | **Currently**: `[capture] rejected ...`, `[matches <skill>'s expected output — ...]`, and (worse) a full dump of every changed-but-unmatched file path (e.g. 25 `screener_cache` HTML paths) print inline with the reply, unconditionally, no gating. #37, not yet fixed. |
| D4 | Same reply, look for markdown syntax rendering | **Currently**: literal `**bold**`, `##`, `\| table \|` syntax shown raw — `rich` is already a dependency but `_run_turn` never renders through it. #38, not yet fixed. |
| D5 | Same reply, look for the "what should I do next" prompt | **Currently**: folded into prose immediately before the (often huge) Sources/disclaimer block — easy to miss entirely. #39, not yet fixed, same output-structure cluster as D2-D4. |

## E. Deterministic scripts / capture infrastructure (#43 — FIXED, #44)

| # | Action | Expected result |
|---|--------|------------------|
| E1 | Pick a concentrated holding (or any symbol), ask for a volatility/drawdown deep dive (portfolio-health-check step 4, or directly: fetch ~1yr OHLCV then `run_volatility`) | **Regression check — should now pass.** Previously crashed on every symbol (envelope unwrap stopped one level short of the bars list). Fixed in `5ff0af8` — confirm `results/<symbol>_volatility_<date>.json` is written with real numbers (return %, max drawdown + dates, daily/annualized vol, worst single day), not a traceback. |
| E2 | `you> what's my thesis on <SYMBOL>` or any thesis-tracker run that writes `workspace/theses/<SYMBOL>.md` | The file is written correctly (thesis-tracker's documented canonical output per CLAUDE.md) — but **currently** the engine's changed-files diagnostic (`_report_changed_files`) flags it as "not matching any known skill's expected output," a misclassification. #44, not yet fixed. Check whether this still fires. |

## F. red-flag-scan governance checklist (#45 — FIXED, closed 2026-09-02)

| # | Action | Expected result |
|---|--------|------------------|
| F1 | Run red-flag-scan (directly, or via a deep-scan turn) on a company with a real, recent cluster of senior-management/director departures (Force Motors was the live example — 11 cessations in one filing day) | **Pass (2026-09-02 re-verification).** Fixed in `d45eff1`, which added `"resignation of director"`/`"resignation of key managerial personnel"` (and auditor variants) to `RED_FLAG_KEYWORDS`. Live-tested on FORCEMOT (same real cluster): scan correctly caught 4 `announcement_keyword` flags — see `workspace/results/red_flags_FORCEMOT_2026-09-02.json`. |

**New gap found during this re-verification (#63, not yet fixed):**
`gsm_surveillance` is incorrectly reported as `checks_skipped` even when
correctly fetched and passed — `_check_surveillance` in
`red_flag_check.py` falsy-checks an empty list (GSM's "clean" shape),
conflating "not on the list" with "couldn't check." ASM never hits this
since its envelope is a dict, not a list.

## G. portfolio-health-check at real scale (#46 — FIXED)

| # | Action | Expected result |
|---|--------|------------------|
| G1 | `you> how's my portfolio doing` on the real 96-holding account | **Regression check — should now pass.** Previously: `get_holdings` returned ~63k characters, the Claude Agent SDK substituted an "exceeds maximum allowed tokens" redirect, the capture was correctly rejected as untrustworthy, and `data/holdings_<date>.json` was simply never written — total skill failure. Fixed in `5ff0af8` via a new `fetch_holdings` tool that fetches in-process and never returns the raw payload to the model. Confirm: the skill completes end-to-end, `data/holdings_<date>.json` contains all 96 holdings, `results/health_check_<date>.json` has real totals. |
| G2 | Immediately after G1, `you> give me the morning digest` | morning-digest also called `get_holdings` directly (same failure mode, found while re-scoping the #46 fix, not part of the original report) — confirm it now also completes successfully on the same account. |
| G3 | `you> what are my holdings` (ad hoc, no skill explicitly invoked) | Confirm the model reaches for `fetch_holdings` (not a "no such tool" error for the now-blocked `get_holdings`) and can still answer from the written file |
| G4 | (Only if a second Zerodha account is ever available) Connect a different account, then repeat G1 | The identity-mismatch guard (#19) should still deny the fetch with "a different Zerodha account is connected" — confirm this still fires now that holdings goes through `fetch_holdings` instead of `get_holdings` directly (this is the one behavior that had to be deliberately preserved during the #46 fix, not just carried over for free) |

## H. Workspace compounding (#40 — deferred, exploratory not pass/fail)

| # | Action | Expected result |
|---|--------|------------------|
| H1 | Run D1's automotive-sector screen, note the date. On a later day, ask a related follow-up (e.g. "what's changed in the automotive sector since last time") | **Currently**: nothing compounds — the screen only leaves `workspace/results/screen_*.json` (never re-read) and a raw, unindexed `workspace/sessions/<timestamp>.md` transcript. Expect the model to have no memory of the earlier screen and re-do the work from scratch. Confirms #40 (no durable research-note bucket, unlike `workspace/theses/<SYMBOL>.md`'s pattern) — ties to the broader #33 roadmap tracking issue, not something to "fix" via this checklist alone. |

## I. First-run explanations (#41 — minor)

| # | Action | Expected result |
|---|--------|------------------|
| I1 | Fresh install, watch the instruments DB build step | **Currently**: prints `instruments=22817 industry_coverage=998 (4.4%, Nifty 500 constituents only)` with no explanation of whether 4.4% is expected/fine for a first-time user. Not yet fixed. |
