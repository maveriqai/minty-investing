# Next Phase — Feature Parity, Workspace Model, Onboarding

*Planning doc, 2026-08-18. Scope: survey what the old `Minty` repo
(`/Users/dhananjaykumar/Minty` on the maintainer's machine — a separate,
earlier codebase, not a branch of this one) has that this repo
(`minty-core`/`minty-investing`) doesn't yet, decide what's actually worth
porting versus obsolete, settle the workspace-model question raised
during live dogfooding, and use both to finalize the onboarding flow. Not
a build queue by itself — each numbered item below still needs its own
scoping pass before work starts, same as this repo's existing docs.*

## 1. Why this doc exists

The FTE (first-time-experience) review closed out 2026-08-18 with the
onboarding flow itself fully live-verified — install, login, Kite connect,
all three skills. Then the maintainer actually used it as a real first-
time user (not a test), and hit friction the review's own testing didn't
surface: unclear whether `minty` needs to run from a specific folder,
Zerodha connection reading as incidental rather than a deliberate step, no
visible confirmation when Claude's already logged in, and — the deepest
one — no clear answer to "what is a workspace and why do I need one."
That last question turned into a real design discussion, which turned up
evidence worth acting on. This doc captures where that landed and what it
implies for what gets built next.

## 2. What's already built here

Three skills (`morning-digest`, `portfolio-health-check`, `red-flag-scan`),
all Layer 1/2 MCP infrastructure (`mcp/kite_gateway`, `mcp/india_price`,
`mcp/india_filings`, `mcp/india_macro`, `mcp/india_news`, `mcp/common`) —
identical to the old repo's, nothing missing there — Minty's own
interactive engine (`engine/interactive.py`, the Phase 1B "Minty owns the
agent loop" work), staged-execution for the digest, tool auto-capture, the
cross-platform reminder system, and a README that's now been live-
dogfooded, not just tested. See `README.md` and `docs/vision.md` for the
current state in full; not re-derived here.

## 3. Feature gap vs. the old `Minty` repo

The old repo has 6 skills; this repo has 3. Diffing `skills/` (identical
list in both repos' `.claude/skills/`, confirmed 2026-08-18):

| Skill | In old repo | In this repo | Verdict |
|---|---|---|---|
| `morning-digest` | ✅ | ✅ | — |
| `portfolio-health-check` | ✅ | ✅ | — |
| `red-flag-scan` | ✅ | ✅ | — |
| `thesis-tracker` | ✅ | ❌ | **Port — high priority.** See §3.1. |
| `screen-indian-stocks` | ✅ | ❌ | **Port — real, additive capability.** See §3.2. |
| `refresh-holdings` | ✅ | ❌ | **Do not port — obsolete.** See §3.3. |

### 3.1 `thesis-tracker` — the highest-value gap

Not just "a missing skill" — per the old repo's `docs/product-
experience.md`, this is the skill that produced the two real proof points
cited for compounding actually working (2026-07-08 and 2026-07-15: a
genuinely separate session picking up an open thread from a prior
session's notes without the user re-explaining context). It's also
directly load-bearing for the workspace decision in §4 — real
usage put two different stocks' theses in one shared workspace, which is
part of the evidence for that decision. Scope: define/update/review an
investment thesis for a held or watchlist name, including a pre-purchase
("watchlist") mode for names not yet bought.

### 3.2 `screen-indian-stocks` — real, additive

Sector/theme-based candidate discovery ("find undervalued auto sector
stocks"). Not tied to anything the new architecture removed — a
straightforward port once scoped against this repo's current Layer 2
tools and instruments-master data.

### 3.3 `refresh-holdings` — obsolete, don't port

Confirmed via `jobs/README.md`'s "Known limitation" section: this skill
exists solely to manually top up a cached holdings snapshot ahead of the
old repo's *unattended* `launchd` digest pipeline, because a headless
`claude -p` run can't complete Kite's browser OAuth flow. This repo
deliberately replaced that entire unattended pipeline with the
reminder-then-manual-trigger model (`docs/vision.md` §2) specifically
*because of* that headless-OAuth limitation, among other reliability
problems. Every digest run here is already interactive with a real Kite
login available — there's no cached-snapshot gap for this skill to fill.
Same reasoning applies to `tools/critic_check.py` in the old repo (a
sanity-check gate needed only because nobody was watching unattended
output live) — not relevant here, don't port either.

### 3.4 Real gaps that exist in *neither* repo yet

Documented in the old repo's `docs/phase2-skill-backlog.md` and
`docs/morning-digest-actionability-plan.md`, explicitly gated behind that
repo's own Phase 2 criteria, never built anywhere: `valuation-screen`
(nothing today helps go from "is X undervalued" to an answer — screen-
indian-stocks discovers candidates, thesis-tracker records an already-
made decision, nothing sits between them), a "what if I add this position
at size X" portfolio-fit preview, and morning-digest reading thesis data
to nudge on new positions with no thesis yet / watchlist names nearing
their stated entry. Real, worth knowing about, **not in scope for this
doc's near-term plan** — they were speculative even in the source repo.

## 4. Workspace model — decision

**Decision: one workspace per install, unnamed, zero setup step.**
`workspace/` (singular, fixed path) is the product surface — no
`/workspace <name>` command, no naming decision for the user to make at
any point.

**Why:**

1. Minty's target user (`docs/vision.md` §1) is one person, one Zerodha
   account, one portfolio — not someone managing several unrelated
   strategies. The Kite connection itself is scoped to the whole install,
   not per-workspace (`data/kite_gateway_session_id.json` at the repo
   root), so workspaces were never a mechanism for separating *accounts*.
2. Routine monitoring and stock-specific research aren't actually separate
   topics for this user — a red-flag-scan on a held stock is directly
   relevant to that stock's place in the daily digest, not an unrelated
   silo. Splitting them would work against compounding, not for it.
3. **Real evidence, not just reasoning:** the old repo's actual ~6-week
   production history never used named workspaces for the automated
   digest at all (`jobs/run_digest.sh` wrote straight to a flat top-level
   `results/`/`data/`, 44+ real digests). And the interactive dogfooding
   that *did* prove compounding — two different stocks' theses — happened
   inside one shared workspace (`portfolio-health-check`), not two
   separate ones, even though the original vision doc imagined one-
   workspace-per-intent. Live-verification testing during the FTE review
   independently landed on the same pattern: one `daily` workspace handled
   routine digests, a portfolio-health-check, and red-flag-scans on three
   different stocks without friction.
4. **No named workspace has ever been used for what naming was built for.**
   Every workspace beyond the default that exists anywhere in either
   repo's history — the FTE review's own `red-flag-scan-live-verify-2`
   through `-5`, `health-check-live-verify-*`, `digest-*`, and similar
   directories — is a testing artifact created to isolate live-
   verification runs from real data, never a deliberate second research
   thread a real user asked for. An escape hatch that's never once been
   exercised for its intended purpose isn't earning the "what do I call
   this" decision it puts in front of a real user — and that decision was
   exactly the friction live dogfooding surfaced in the first place ("why
   do I need a workspace at all," "what is this daily workspace supposed
   to be").

**Mechanism:** keep `resolve_workspace(name)` and the underlying
multi-workspace machinery in `engine/workspace.py` alive, but only as an
internal/dev capability — needed for the kind of test isolation the FTE
review's live-verification runs relied on — reachable through something
like an env var override (`MINTY_WORKSPACE=test-scratch minty`), never a
conversational `/workspace <name>` command. A real user never sees or
makes this decision. One naming detail worth deciding deliberately, not
inheriting by accident: this machinery still writes to the existing
`workspaces/` (plural) directory, which now sits right next to the new
singular `workspace/` — close enough to invite a real mix-up in code, in
`.gitignore` patterns, or in a directory listing. Worth renaming the
dev-only sandbox to something visibly distinct (e.g. `.dev-workspaces/`)
rather than keeping two directories one letter apart.

**Internal layout — split only where there's a real correctness reason
to, not by skill.** The deciding property isn't "which skill produced
this file" — it's whether
the content is a **living document that gets read, merged, and rewritten
over time**, or a **point-in-time snapshot written once and never touched
again**. Only one thing in the current-plus-planned skill set has the
first shape:

- **`thesis-tracker`** reads an existing thesis, merges new evidence in,
  and rewrites it — the one place cross-instance collision is a real risk
  (one symbol's merge accidentally clobbering a different symbol's
  section). Gets its own file per symbol: `workspace/theses/<SYMBOL>.md`.
  Real old-repo evidence supports splitting it out now rather than
  waiting for a problem: two concurrent theses (CUPID, KEI) already
  coexisted as separate sections competing for space in one shared
  `notes.md` — not yet under real growth pressure, but splitting removes
  both the merge-collision risk and CLAUDE.md's ≤2000-word ceiling as a
  constraint on how many theses can be tracked at once, before either
  actually bites.
- **Everything else** — `morning-digest`, `portfolio-health-check`,
  `red-flag-scan`, `screen-indian-stocks` — writes independent,
  date-stamped files, never edited after the fact (no merge, so no
  collision risk a folder boundary would protect). These stay flat in
  `workspace/results/`, distinguished by their existing filename-prefix
  convention (`digest_<date>.json`, `health_check_<date>.json`,
  `red_flags_<SYMBOL>_<date>.json`, `candidates_<industry>_<date>.json`)
  — already effectively filterable (`ls results/*CUPID*`,
  `ls results/*2026-07-09*`) without physical folders. Real old-repo
  evidence favors this too: `workspaces/portfolio-health-check/results/`
  mixed digest, health-check, red-flag, and thesis outputs for the same
  stretch of research in one folder, and that's the compounding story
  working, not clutter — everything about the same research thread
  sitting in the same neighborhood. Skill-based folders would scatter it
  instead (`results/morning-digest/`, `results/red-flag-scan/`, ...) with
  nothing gained in exchange, since there's no merge risk to protect
  against. Revisit only if flat `results/` genuinely becomes hard to scan
  once months of real daily usage accumulate — an observable trigger, not
  a hypothetical one, so not something to pre-solve now.
- One loose end, not a redesign: the old repo's `workspaces/portfolio-
  health-check/` also has a `scripts/sector_concentration.py` — a
  workspace-local `scripts/` folder that isn't part of the documented
  convention (a skill's *own* deterministic scripts already live under
  `skills/<name>/scripts/`, not inside any workspace). Looks like a
  one-off the model wrote itself mid-session, not a designed pattern.
  Worth an explicit call when thesis-tracker/screen-indian-stocks are
  actually ported: either bless a workspace-local `scripts/` as a real
  category (for genuinely ad hoc, symbol-specific analysis a skill can't
  fully anticipate) or treat it as old-repo drift to not reproduce.

**`notes.md` — one file, not two, plus one thing pulled out of "notes"
entirely.** The old two-tier split (root `notes.md`/`preferences.md` for
durable cross-workspace facts, `workspaces/<name>/notes.md` for
topic-scoped findings) existed to solve a problem — "what carries across
workspaces" — that mostly dissolves once there's only one workspace.
What's actually in today's root `notes.md`, on inspection, is two
different kinds of thing wearing one label:

- The **Zerodha account anchor** (`user_id`, `user_name`, `email`) isn't
  something a user reads or edits — it's a machine safety check
  (morning-digest step 3 compares it before trusting fetched data and
  stops on mismatch). It was never really a "note." Pulled out into its
  own engine-managed file, `data/account_identity.json` — same pattern as
  the existing `data/kite_gateway_session_id.json` (small JSON, the
  engine reads/writes it directly, never exposed through the model's
  plain `Read`/`Write`), sitting in the top-level `data/` alongside that
  file since it's install-wide infrastructure, not workspace content.
  This also closes a real robustness gap found while reviewing the
  mechanics: unlike workspace paths (hardened via `WORKSPACES_ROOT`, an
  absolute path computed from the engine module's own file location,
  cwd-independent), today's root `notes.md` goes through plain
  `Read`/`Write` with no `cwd` ever set on `ClaudeAgentOptions` — so its
  location isn't actually guaranteed to resolve correctly if `minty` runs
  from outside the repo, the same class of bug `update_workspace_notes`
  was built to close on the workspace side. Moving to an engine-owned,
  absolute-path-resolved file fixes this by design, not by patching the
  old mechanism. (A code-reading inference, not live-confirmed as a bug —
  moot either way once this lands.)
- **Preferences** (the one real example so far: morning-digest's "≤2
  minutes" length preference) stay as a `## Preferences` section inside
  the one `workspace/notes.md` — not a separate `preferences.md`. The old
  repo's own docs describe what "preferences" was meant to hold: nudge
  toggles, move/entry-point thresholds, feed source config
  (`docs/product-experience.md`, `docs/research-intake-backlog.md` open
  question 12) — none of which exist in minty-investing (all
  Phase-2-gated, see §3.4) — and `preferences.md` itself was **never
  populated** in the old repo's ~6 weeks of real production use (that
  repo's own `workspaces/portfolio-health-check/notes.md` explicitly
  notes "root `notes.md` → Investor profile doesn't have yet"). The one
  real preference that got used bypassed the dedicated file and went
  straight into prose notes anyway. No evidence a separate structured
  file is needed yet — revisit only once an actual toggle/threshold
  feature gets built and needs a real settings surface.

Resulting shape:

```
data/                        # unchanged, install-wide infra — instruments.db,
                              #   kite_gateway_session_id.json, + new account_identity.json
workspace/                   # singular, one per install, no naming step
  notes.md                   # ## Preferences + any other small, durable,
                              #   non-multiplying fact
  theses/
    CUPID.md
    KEI.md
  data/                      # raw tool captures — unchanged convention
  results/                   # computed artifacts — unchanged convention, flat
```

**Mechanical implications — two things not designed in detail, both real
scoping work for whoever picks up §6 item 1:**
- `update_workspace_notes` (`engine/workspace_notes.py`) currently
  hardcodes exactly one path (`workspace_root/notes.md`). It needs to
  generalize to accept a target within a small, allow-listed set
  (`notes.md`, `theses/<SYMBOL>.md`) rather than either staying
  hardcoded to one file or opening up to an arbitrary path — same
  "engine decides where, model decides what" property as today, just
  parameterized.
- `data/account_identity.json`'s actual write path isn't specified
  either. The obvious option is extending `tool_capture.py`'s existing
  auto-capture mechanism — add a `(kite_gateway, get_profile)` →
  `data/account_identity.json` entry to `CAPTURE_SPECS`, reusing
  machinery that already exists rather than building a new tool. But
  that machinery is currently built around `workspace_root`-relative
  paths (every other capture lands under `workspace/data/`), and this
  one needs to be workspace-*independent* — top-level `data/`, per the
  "Resulting shape" diagram above — so it likely needs
  `tool_capture.py`'s own path resolution extended to support a
  workspace-independent target, not just a one-line `CAPTURE_SPECS`
  addition. Needs a real look at `engine/tool_capture.py` before
  assuming this is small.

**Execution pattern for ported skills — plain, not staged, by default.**
`stages` (`docs/staged-skill-execution-design.md`) exists to fix a
specific, *observed* failure mode — a single turn accumulating enough
tool calls (98-holding morning-digest, ~70 calls) to disrupt the engine's
own tool-call/tool-result pairing — not as a default execution mode for
anything with more than one tool call. Checked both candidates against
that bar:
- **`thesis-tracker`**: inherently scoped to one symbol (occasionally a
  short watchlist) per invocation — nowhere near the call volume that
  triggered staging. Plain `expected_outputs`/`deterministic_scripts`
  frontmatter, same as `portfolio-health-check`/`red-flag-scan` today.
- **`screen-indian-stocks`**: bounded by its own existing 25-candidate
  default cap (`scripts/list_candidates.py --limit 25`, chosen "to keep
  polite to yfinance") — roughly 25 single-symbol `get_fundamentals` calls
  plus one batched `get_quote` call per run. Noticeably fewer than
  morning-digest's ~70, and the cap is already a deliberate ceiling in the
  skill's own design, not an accident. Plain frontmatter here too.
  Genuine risk to flag, not fix now: the skill's own instructions let the
  cap be raised "if the user explicitly asks for a wider sweep" — that
  escape hatch is exactly the kind of unbounded-turn scenario staging
  exists for, so if a wide-sweep screen turns out to be a real, repeated
  ask once this ships, that's the trigger to revisit staging for this one
  skill specifically — not a reason to stage it preemptively today.

## 5. Onboarding flow implications

Once §4 lands in code (`workspace/` becomes the one fixed, unnamed
location — no `/workspace <name>` command anywhere in the product
surface), the Onboarding section of `README.md` collapses from four steps
to three. The workspace explanation currently in step 2 (added
2026-08-18, see git history) doesn't move somewhere else in the doc — it
goes away entirely, concept included, not just the step. That's the
actual point of §4: under the old model, live dogfooding's own complaint
("what is this daily workspace supposed to be") existed because the user
had to make a decision (`/workspace daily`) about something undocumented;
under §4 there's no decision left to make, so there's nothing left to
explain. The word "workspace" doesn't appear anywhere in the three steps
drafted below, on purpose. (One place it's *not* fully invisible: "How
the `minty` command finds your data" still needs a `workspaces/` →
`workspace/` terminology fix — a wording correction, not a
reintroduction of the concept to the user — see §5.3.)

The other three findings from live dogfooding (folder-location clarity in
step 1, Zerodha connection as its own deliberate step, the "Claude account
already connected." confirmation message) are already fixed and shipped
independently of this doc — see commits from 2026-08-18 in `git log`.

### 5.1 Kite connection status check — mechanism

Landed on a fully deterministic version of this, not the MCP-call-based
one first proposed (calling `kite_gateway.get_profile` on a hidden
startup turn). The engine checks two local files at startup — no MCP
session, no model turn, the same "check before printing anything" shape
`ensure_logged_in()` already uses for Claude — and prints one of two
lines immediately after the Claude confirmation, before "Minty —
connected.":

- **Both `data/account_identity.json` and the newest
  `workspace/data/holdings_*.json` exist:** `Holdings for account <user_id>
  found — last refreshed <N> day(s) ago.` `<N>` comes from the date
  embedded in the holdings filename, not the file's mtime — mtime can get
  reset by a git operation or a file copy and would silently misreport
  freshness; the filename's date is the actual fact being reported.
  Deliberately doesn't claim the Kite session is still live — Kite forces
  a daily re-login, so the engine can't actually know that without a real
  API call, and overclaiming "connected" would be exactly the kind of
  ungrounded statement this project otherwise refuses to make. Stating a
  fact with its age instead ("found," "last refreshed") stays true
  regardless of whether the underlying session has since expired.
- **Neither file exists:** `Zerodha not connected yet — ask something
  like "what are my holdings" anytime to connect, or skip for now and
  you'll be prompted when you need it.` Not gated on "is this literally
  the first run ever" — there's no separate flag for that, and none is
  needed. The same file-existence check just keeps producing this line
  every session until the user actually connects, then flips permanently
  to the first branch. This is what actually answers the original
  dogfooding complaint (Zerodha connection wasn't a deliberate, visible
  step) for a genuinely new install, without inventing new persisted
  state to track "have I asked before."

One state this binary doesn't cleanly cover: `account_identity.json`
exists but no holdings file does (an empty portfolio, or an interrupted
first connection). Falls through to the second branch — the practical
next action for the user is the same either way ("ask a holdings
question"), so a third message isn't worth building for a state this
rare.

Neither branch blocks anything — both print, then the normal `you>`
prompt follows immediately either way. Unlike Claude's login (a hard
requirement — nothing works without it), Kite connection is optional at
this layer: `screen-indian-stocks` never touches it at all. If the user
ignores the nudge, today's reactive fallback (asking a holdings-shaped
question later still triggers the same login-link flow) still catches it
— this is additive, not a replacement.

`data/account_identity.json` (introduced in §4 to fix a robustness gap in
the old root-`notes.md` identity anchor) now has a second real reason to
exist beyond that fix — it's a direct input to this check.

### 5.2 Target `README.md` Onboarding section (ready to land once §4 ships)

```markdown
## Onboarding

Three steps, in order, from a fresh install to your first real result.

1. **Confirm Claude is connected.**
   ​```bash
   minty
   ​```
   Run this from wherever you like — the repo folder Quickstart just left
   you in, or any other directory on your machine. Location genuinely
   doesn't matter (see "How the `minty` command finds your data" above).

   Minty checks your Claude login itself before printing anything else.
   Already logged in (the common case)? You'll see `Claude account
   already connected.` followed by `Minty — connected.` Not logged in?
   Minty runs `claude auth login` for you and waits — you still complete
   the real sign-in in your own browser, this just saves you the extra
   step of running it yourself, and there's no lingering `claude` chat
   session to get stuck in afterwards. If login still doesn't take,
   Minty exits with `Couldn't sign in to Claude — run 'claude auth
   login' and try again.` — run that yourself, then rerun `minty`.

2. **Connect your Zerodha account.** Minty checks this automatically too,
   the moment it starts — right after the Claude confirmation you'll see
   one of two lines:
   ​```
   Holdings for account AB1234 found — last refreshed 2 days ago.
   ​```
   (already connected — nothing to do), or:
   ​```
   Zerodha not connected yet — ask something like "what are my holdings"
   anytime to connect, or skip for now and you'll be prompted when you
   need it.
   ​```
   If you see the second line, connect the same way Claude's login in
   step 1 worked — ask for anything that needs live account data and
   Minty prompts you:
   ​```
   you> what are my holdings
   ​```
   Minty replies with a one-time Kite login link. Click it, log in in
   your own browser (Minty never sees your Zerodha credentials), then
   tell Minty you're done — it picks up from there. Once connected, this
   persists across sessions until Kite's own daily re-login requirement
   kicks in — you won't repeat this every conversation.

3. **Run your first skill.**
   ​```
   you> give me the morning digest
   ​```
   or `how's my portfolio doing` / `any red flags on RELIANCE`. That's
   the whole loop from here — ask in plain language, get back a grounded,
   sourced answer. Everything you do compounds automatically from here —
   what Minty finds, and anything durable you tell it, carries into your
   next conversation with no setup on your part. It all stays on your
   machine, in this repo, never uploaded anywhere.
```

Step 1's copy carries over unchanged (already live-verified 2026-08-18).
Step 2 is new — §5.1 covers the mechanism behind it — and needs its own
live verification once built, both branches (fresh install and
already-connected), not just the already-connected path the old draft
happened to be tested against.

### 5.3 Other user-facing text that has to change in step with §4

Found while drafting §5.1 — none of these are optional once §4 lands,
since leaving any one of them unchanged would either break or contradict
the three-step flow above:

- **The REPL's own banner line** (`engine/interactive.py`'s `_repl()`)
  currently reads `"Minty — connected. Type a message, 'exit' to quit, or
  '/workspace <name>' to set the active workspace."` — the `/workspace
  <name>` clause needs to come out; that command shouldn't exist in the
  product surface at all per §4.
- **Three skills' own SKILL.md step 1** — `morning-digest`,
  `portfolio-health-check`, and `red-flag-scan` each open with "Confirm a
  workspace... If no workspace is open, ask the user to open or create
  one." Under §4 a workspace is always open (fixed, engine-created before
  the model ever sees a turn) — that branch can never fire again and the
  step becomes dead instruction. Needs rewording once §4 lands, not left
  as an unreachable step describing a decision that no longer exists.
- **Prerequisites item 4** in `README.md` currently cross-references "Onboarding
  step 3" for the Zerodha connection — becomes step 2 under this shape.
- **"How the `minty` command finds your data"** (the section right above
  Onboarding) currently says `workspaces/` (plural) in its cwd-independence
  explanation — becomes `workspace/` (singular). The explanation itself
  (an editable install always points at the repo it came from, regardless
  of invocation directory) still holds and doesn't need re-deriving, just
  the terminology fixed to match.

## 6. Suggested sequencing

Not a hard order, but a reasonable one given dependencies. §4 is several
coupled engine changes, not one:

1. **Workspace collapse (§4)** first — it's a precondition for everything
   after it, and touches several files: `engine/interactive.py` (drop
   `/workspace <name>` and its REPL banner mention, point at the fixed
   `workspace/` path; also add the Kite connection status check from
   §5.1 to `main()`, right after the Claude login check),
   `engine/workspace.py` (single-workspace constant + the dev-only env
   var override, sandboxed under a distinctly-named directory per §4's
   naming note), `engine/workspace_notes.py` (generalize
   `update_workspace_notes` to an allow-listed target: `notes.md` or
   `theses/<SYMBOL>.md`), `engine/tool_capture.py` (extend its path
   resolution to support the workspace-independent
   `data/account_identity.json` target — see §4's "Mechanical
   implications"), the resulting `data/account_identity.json` mechanism
   itself, which replaces the identity-anchor read/write currently in
   root `notes.md` (morning-digest's SKILL.md step 3 needs updating to
   match — and this file is now also §5.1's own dependency, not just a
   robustness fix), and all three skills' own SKILL.md step 1 ("Confirm a
   workspace... if none is open, ask") — that branch can no longer fire
   under §4 and needs rewording, not left describing a decision that no
   longer exists (§5.3). Do this before the doc rewrite below so
   Onboarding only gets rewritten once.
2. **Onboarding README rewrite (§5.2/§5.3)** once #1 lands — drop in the
   drafted three-step Onboarding text (§5.2) plus §5.3's remaining two
   README-side fixes (Prerequisites' step cross-reference, and "How the
   `minty` command finds your data"'s `workspaces/` → `workspace/`
   wording — §5.3's other two items, the REPL banner and the three
   skills' dead step, are engine/skill changes already covered in #1),
   then verify the resulting flow live from a fresh clone — both of §5.1's
   branches, not just one — the same way the rest of this review was
   verified.
3. **`thesis-tracker` port (§3.1)** — highest-value skill gap, exercised
   against `workspace/theses/<SYMBOL>.md` directly (§4's layout), and a
   natural place to re-confirm compounding still holds under the new
   model (a smaller version of the old repo's own 2026-07-08/07-15
   proof).
4. **`screen-indian-stocks` port (§3.2)** — independent of the above, can
   happen in parallel or after #3.
5. Phase-2-gated items in §3.4 stay out of scope until their own gating
   criteria are revisited — not part of this plan.

## 7. Open questions

- Whether `update_workspace_notes` should take a single generalized
  `target` argument constrained to an allow-listed set, or split into two
  small dedicated tools (`update_workspace_notes`, `update_thesis`) —
  not designed yet, real work item for §6 item 1.
- Whether the dev-only workspace-override mechanism (env var, per §4) is
  the right shape for test isolation, or whether a CLI flag or something
  else is more ergonomic — won't really be known until whoever does §6
  item 1 has actually used it once.
- Whether `thesis-tracker`'s pre-purchase/watchlist mode needs any new
  Layer 2 data this repo doesn't already have, or ports cleanly on
  existing tools — needs a scoping read of the old repo's
  `skills/thesis-tracker/SKILL.md` before starting.
- Whether `screen-indian-stocks` needs anything beyond the instruments
  master + existing fundamentals tools already available here.

## 8. Open thread: session transcripts and memory

A separate thread from the feature-gap/workspace work above — genuinely
new territory, nothing today addresses either half of it. Worth keeping
the two halves distinct rather than solving them as one feature, since
they answer different questions and have different failure modes if built
wrong:

- **Session transcripts** — a raw, complete record of what was
  asked/answered in a given `minty` session. Nothing today persists this;
  a session lives entirely in the FIFO/REPL process and is gone once it
  exits, aside from whatever a skill deliberately wrote to `data/`,
  `results/`, or `notes.md` along the way. The value case is audit/debug
  ("what exactly did Minty tell me last Tuesday," reconstructing a prior
  conversation verbatim) — not compounding research value, since a raw
  transcript is exactly the kind of unstructured, re-derivable content
  CLAUDE.md's notes guidance already says *not* to save to notes.md
  (prices, one-off results, anything stale next turn). If built, this
  should be its own mechanism — e.g. `workspace/sessions/<timestamp>.md`
  written by the engine itself, not routed through notes.md — kept firmly
  separate from the compounding-memory path so the two don't get
  conflated later. Already covered by the existing git-ignore/local-only
  rule for `workspace/` (§4) — no new privacy surface, same
  personal-financial-data sensitivity as everything else already in
  there.
- **"Adding a memory"** — read as something more ambitious than
  transcripts: an automated extraction layer that watches a session and
  writes durable facts into notes.md itself, closer to how a coding-agent
  harness's own auto-memory feature works for its user, rather than
  the current model where a skill's own SKILL.md steps are what update
  notes.md (thesis-tracker's step 5, e.g.). Real potential upside — it
  would remove "did the skill remember to write this down" as a failure
  mode — but real cost too, and it cuts against a design choice CLAUDE.md
  already made deliberately: notes.md stays small (≤2000 words),
  hand-curated, and explicitly excludes exactly the kind of raw,
  point-in-time content an automated extractor would be tempted to save.
  The two real compounding proof points this project has (old repo,
  2026-07-08/2026-07-15) came from the plain manual model working fine —
  no evidence yet that automation is solving a problem that's actually
  been hit. Recommend treating this as a real but low-priority idea, not
  sequenced into §6 — revisit if/once thesis-tracker is ported and in real
  use here and a specific "the model forgot to update notes.md" failure is
  actually observed, the same evidence-before-building pattern the
  workspace decision itself (§4) was made on.

Not sequenced into §6 either way — flagged here so the distinction isn't
lost before it's picked up.
