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
