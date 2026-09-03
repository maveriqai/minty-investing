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

## F. red-flag-scan governance checklist (#45, #63 — FIXED, closed 2026-09-02)

| # | Action | Expected result |
|---|--------|------------------|
| F1 | Run red-flag-scan (directly, or via a deep-scan turn) on a company with a real, recent cluster of senior-management/director departures (Force Motors was the live example — 11 cessations in one filing day) | **Pass (2026-09-02 re-verification).** Fixed in `d45eff1`, which added `"resignation of director"`/`"resignation of key managerial personnel"` (and auditor variants) to `RED_FLAG_KEYWORDS`. Live-tested on FORCEMOT (same real cluster): scan correctly caught 4 `announcement_keyword` flags — see `workspace/results/red_flags_FORCEMOT_2026-09-02.json`. |

**Gap found during this re-verification, fixed same day (#63, closed
2026-09-02):** `gsm_surveillance` was incorrectly reported as
`checks_skipped` even when correctly fetched and passed —
`_check_surveillance` in `red_flag_check.py` falsy-checked an empty list
(GSM's "clean" shape), conflating "not on the list" with "couldn't
check." ASM never hit this since its envelope is a dict, not a list.
Fixed in `a023aa4` (checks `data is None` instead of falsy-checking the
unwrapped result) with a regression test. Live re-verified two ways:
(1) rerunning the script directly against the exact real GSM capture
that originally reproduced the bug (`workspace/data/
surveillance_gsm_2026-09-02.json`, FORCEMOT) now yields
`gsm_surveillance` in `checks_performed`; (2) a fresh full skill run on
TATAMOTORS (`workspace/results/red_flags_TATAMOTORS_2026-09-02.json`)
shows `gsm_surveillance` in `checks_performed` end to end, and the
model's reply correctly narrates it as "ran clean," not "couldn't
check."

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

## J. Session #64-#74 fixes (2026-09-02, this session — FIXED, re-verify live)

Derived from the same 2026-09-02 live test's remaining findings, triaged
into issues #64-#77 and fixed the same day. Each row below traces to a
specific commit — check off as you go; note any deviation directly below
the row.

| # | Action | Expected result |
|---|--------|------------------|
| J1 | Get the model to stage a memory candidate without an explicit "remember" ask — e.g. after a portfolio-health-check run, mention in passing "I think I'm too heavy in PSU banks, might trim next quarter." Then `exit` and start a fresh `minty` session. | **PASS (2026-09-03, live-verified).** (#65, `30eb5b4`) The review turn's reply ends with the SEBI disclaimer, rendered dimmed/italic and visually separated from the main text. Confirmed via `workspace/sessions/2026-09-03T13-58-16.md`: the disclaimer appears, and the tool-call log shows zero tool calls during that turn — proving it came from the new `force_disclaimer` path, not an incidental capture. Wording fix also confirmed: the reply opened with "These findings are already captured in their source files either way; the only question is whether to also promote them into your curated `notes.md`," with an inline "(Already in: ...)" per candidate — no more "isn't this already saved?" confusion. Visual dim/separated rendering confirmed live in iTerm. Bonus: the same session's later spontaneous "I think I'm too heavy in PSU banks" correctly went through `stage_memory_candidate`, not a direct `notes.md` write — confirms #64's reclassification held. |
| J2 | `you> give me the morning digest` (a few times if needed, to catch a transient tool hiccup) | **PASS (2026-09-03, live-verified).** (#66, `6c31dfd`) `workspace/results/digest_<date>.md` starts cleanly with `# Morning Digest` — no stray recovery/narration text, even if a tool call needed a retry mid-turn. This run was a genuine reproduction, not a lucky clean pass: the compose stage's tool-call log (`2026-09-03T14-10-19_tool_calls.jsonl`) shows 4 failed `Glob` calls (relative paths resolving outside the workspace, denied by #55's scoping hook) before it corrected to an absolute path and succeeded — exactly the retry sequence that used to leak into the saved file. `digest_2026-09-03.md` and the chat-visible reply were both clean anyway, and no `[compose]` fallback diagnostic printed anywhere in the session, confirming the model emitted the `<!-- minty:compose-final -->` marker and the stripping logic used it. (The underlying Glob false-negative itself is still open as #79 — it recurred here as expected; only the leaked-text symptom needed to not reproduce, and it didn't.) |
| J3 | Ask for daily OHLCV over a long range likely to exceed the token cap for one symbol (e.g. 5 years) — directly, or via portfolio-health-check's volatility deep dive on a real concentrated holding | **PASS (2026-09-03, live-verified).** (#67, `a1278e3`) Tested with "analyze daily ohlv of sanduma and cupid for last 10 years" — both hit the SDK's "exceeds maximum allowed tokens" redirect (69K and 216K chars). Tool-call log (`2026-09-03T14-01-49_tool_calls.jsonl`) shows the model went straight to a narrower retry (1yr window, then yearly chunks) for both symbols with **zero `Read` attempts** on either overflow path anywhere in the sequence. Chat reply also narrated the reason clearly ("too large to pull in one shot... I'll fetch it in yearly chunks instead"). Side note, not a J3 failure: two `Glob` "No files found" calls appeared later in the same sequence — more evidence for the still-open #79. |
| J4 | Run `screen-indian-stocks` on a sector, then `red-flag-scan` on one holding, then `portfolio-health-check` | **PASS (2026-09-03, live-verified).** (#68, `166f686`) All three confirmed with explicit save lines: screen-indian-stocks (EV→automotive screen) ended "Saved to `research/sectors/automobile-and-auto-components.md` (new dated entry appended, prior content untouched)"; red-flag-scan (FORCEMOT) ended "Saved to `research/stocks/FORCEMOT.md`" + "Research note updated with today's re-scan appended (prior entries untouched)"; portfolio-health-check ended "Saved to `notes.md`" (same run reviewed under J1). None silent this time. |
| J5 | Run `screen-indian-stocks` on a sector you haven't screened before in this workspace (so step 3's prior-research `Read` correctly misses); separately, ask any ad hoc Kite-dependent question before logging in | **PASS (2026-09-03, live-verified).** (#69, `a351944`) Cold-start case: FMCG sector screen's `Read` on `research/sectors/fast-moving-consumer-goods.md` failed with "File does not exist" (confirmed in the tool-call log), scenario set up correctly. Pre-login case: temporarily renamed `data/kite_gateway_session_id.json` aside, exited and restarted `minty` (needed since the running `kite_gateway` subprocess caches its session in memory and ignores the file until restart), then ran `you> what are my holdings`. Screenshot confirms the terminal printed exactly `[note] mcp__identity_check__check_identity_match — kite_gateway.get_profile error: Please log in first using the login tool (expected, not a problem)` — not the old alarming `[audit] tool error: ...` form. Session file restored afterward. |
| J6 | Any reply with a real Sources footer (e.g. `you> what are my holdings`) | **PASS (2026-09-03, live-verified after 4 follow-up fixes).** (#70 partial) Started conditional-fail: `you> what are my holdings` answered from cached data with no fresh captures, so the engine's own footer never fired and the model's self-authored "Sources:"/disclaimer rendered undimmed. Chain of fixes, each caught by re-testing the previous one rather than assumed correct: (1) `783c34e` — `_split_footer` detects a self-authored footer via `DISCLAIMER`'s own text, folding in a preceding "**Sources" line if present; (2) `3322afe` — fixed a regression the first fix introduced (a self-authored trailing `Next:` line got swallowed into the dimmed block instead of its own panel); (3) `ab7f442` — a *more serious* gap found live: some "what are my holdings" runs shipped with **no disclaimer at all**, since `captures` never reflects Minty's own internal tools (`fetch_holdings`, `run_health_check`) — `send()` now also forces the bare disclaimer whenever a turn makes any tool call, not just a Layer-2 capture; (4) `8ce2ee9` — screenshot showed the dimmed footer sitting with no visual gap under the body; added an explicit blank line between them. Final live confirmation: disclaimer present every time, dimmed correctly, "Next:" in its own panel, clear visual gap from the body. The dimming mechanism for a normal *engine*-appended footer was already confirmed separately in J2/J4/J8. (Other #70 items — markdown-rendering consistency, clickable links, turn-boundary separators — remain open.) |
| J7 | `you> /feedback the login link wasn't clickable in my terminal`, then separately `you> /feedback` with nothing after it | **SKIPPED (2026-09-03)** — live feedback during testing: a local-only file nobody reviews isn't actually helpful ("record only feedback is not helpful"). Reopened #73 rather than closing it as satisfied; a redesign (e.g. printing a pre-filled `gh issue create` command) is planned but not done yet — do not mark this row pass/fail until that lands and gets re-tested. |
| J8 | `you> what have you already researched about <a sector/stock you screened earlier in this session>` — and separately, the same question about something you've never touched | **PASS (2026-09-03, live-verified).** (#74, `5a7931a`) "what have you researched on pharma" (uncovered): tool log shows `Glob` across `research/**/*.md`, `theses/*.md`, `notes.md` before answering; reply correctly said "No dedicated pharma research exists yet" with an accurate breakdown of what does/doesn't exist, not a guess. "what have you research about automotive sector" (covered): tool log shows `Read` on `research/sectors/automobile-and-auto-components.md`, `research/stocks/TATAMOTORS.md`, `research/stocks/FORCEMOT.md`, `theses/FORCEMOT.md` before compiling an accurate, thorough summary of both sector- and stock-level research from earlier in this session (J4/J5). Both cases checked real files rather than answering from conversation memory. |

## K. `/feedback` redesign — evidence-backed, reviewed, opt-in GitHub issue (#73, 2026-09-03)

Live re-test of the #73 redesign built after J7's rejection ("record only
feedback is not helpful"). `maveriqai/minty-investing` is public, so the
share step (K3) will succeed for any authenticated `gh` account, not just
a collaborator — use a throwaway/obviously-a-test note for K3, since it
creates a real, publicly visible issue.

| # | Action | Expected result |
|---|--------|------------------|
| K1 | `you> /feedback the login link wasn't clickable in my terminal`, then answer `n` (or just decline) at the "look at this session's transcript..." prompt | **PASS (2026-09-03, live-verified).** Not run with the suggested throwaway note — instead the tester hit a real bug live (see K-bonus below) mid-typing and declined analysis on that attempt. Confirmed via `workspace/sessions/2026-09-03T16-57-52.md`: the 16:59 review turn's own evidence block reads `(no transcript yet this session)`/`(no tool calls yet this session)`, proving no earlier turn was sent for the declined 16:58 note — it only landed as a raw entry in `workspace/feedback.md` ("the initial loading on first typing minty the doesn"), exactly the decline path's contract. |
| K2 | `you> /feedback <some other note>`, answer `y` to the evidence prompt, read the drafted title/body Minty shows you, then say no when it asks about sharing | **PASS (2026-09-03, live-verified).** Second `/feedback` in the same session ("there should be a way to see files written by minty") — its review turn's evidence block contains the *real* prior transcript/tool-call content (not placeholders), confirming evidence aggregation genuinely reflects this session's own history across multiple `/feedback` calls, not just a fresh-session stub. Tool-call record: `"share": false`, `"result_preview": "Saved locally — not shared with the Minty team."`. `workspace/feedback.md` entry ends "Not shared with the Minty team (kept local only)." — matches. |
| K3 | Same as K2 but say yes to sharing, with an obviously-a-test note (e.g. "test: verifying the new /feedback share flow, safe to close") | **PASS (2026-09-03, live-verified).** Real note used instead of a throwaway one (see K-bonus) — `mcp__feedback_issue__file_feedback_issue` tool-call record shows `"share": true`, `"is_error": false`, `"result_preview": "Filed: https://github.com/maveriqai/minty-investing/issues/80"`. Confirmed live on GitHub: issue #80, open, title matches exactly. `workspace/feedback.md`'s entry ends `Shared as: https://github.com/maveriqai/minty-investing/issues/80`, matching. Left open rather than closed — real, useful feedback, not a disposable test (see below). |
| K4 | Repeat K3's flow but launch this one run with `gh` hidden from `PATH` (`PATH="$(echo "$PATH" \| sed 's\|:/opt/homebrew/bin\|\|; s\|/opt/homebrew/bin:\|\|')" minty`) so the call fails without touching your real `gh` auth state | **PASS (2026-09-03, live-verified).** Tool-call record: `"share": true`, `"status": "completed"`, `"is_error": false` (never surfaced as a fault), `"result_preview"` starts `"Couldn't file it automatically ([Errno 2] No such file or directory: 'gh') — saved locally instead. Run this yourself to share it: ..."` — the real `OSError` from the missing binary, caught cleanly. No crash, no `[audit] tool error:` line, session continued normally afterward. `workspace/feedback.md` entry ends with the fenced `gh issue create --repo maveriqai/minty-investing --title '...' --body '...'` fallback command, correctly `shlex.quote`d around a multi-line body. |
| K5 | `you> /feedback` with nothing after it | **PASS (2026-09-03, live-verified via screenshot).** Terminal shows `you> /feedback` immediately followed by `Usage: /feedback <what you want to report> — e.g. /feedback the login link wasn't clickable` and straight back to `you>` — no evidence-confirm prompt appeared, exactly the expected no-op. |
| K6 | Regression: a plain multi-turn conversation with no `/feedback` anywhere (e.g. two or three ordinary questions), in the same session as some of K1-K5 | **PASS (2026-09-03, live-verified).** Same session, after K3: `what are my holdings` and `whats the latest with reliance` both answered normally — holdings reply carries the SEBI disclaimer, RELIANCE reply carries a full Sources list + disclaimer, both formatted exactly as J-series turns. No `/feedback`-review language leaked into either. |

**K-bonus — real feedback surfaced during testing, not a scripted case.** The tester's actual `/feedback` note (declined-then-retried) reported two genuine gaps: (1) input isn't blocked while Minty is still starting up, so typing can start before the REPL is ready — plausibly what garbled the first attempt's own note text; (2) no way to edit a `/feedback` note before it's captured, once you've started typing it. Both filed as [issue #80](https://github.com/maveriqai/minty-investing/issues/80) by the flow itself — a real demonstration of K3 working end-to-end on real input, not just a synthetic test string.
