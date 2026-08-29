# Minty v2 — Skill Specs

Companion to `vision.md`. One consistent template per skill, kept separate
from the vision doc so it stays scannable as skills are added later.

## Template

- **Name & trigger** — one line on when someone reaches for this vs.
  another skill (avoids ambiguity that would otherwise need a paragraph to
  resolve later)
- **Input** — which Layer 1/2 tools it calls, and what the user supplies
  (symbol, sector, etc.)
- **Output shape** — what it actually produces (a brief, a table, a flag
  list)
- **Grounding rule** — what must be computed in code vs. narrated by the
  model, specific to this skill
- **v1 priority** — must-have / later
- **Staged? (optional)** — only relevant if a single run's tool-call count
  can grow large enough (roughly: dozens of calls, or scales with
  portfolio/holding count) that one continuous turn risks the same
  context-bloat failure `morning-digest` hit at real scale (see
  `docs/staged-skill-execution-design.md`). If so, declare a `stages:`
  block in the skill's own `SKILL.md` frontmatter — each stage an `id`, an
  authored `instructions` block, and optional `needs`/`produces` file
  patterns (the same glob-with-placeholders shape as `expected_outputs`)
  describing what it reads from and writes to disk. The engine picks this
  up automatically: a staged skill is exposed only via its own
  `run_staged_<skill>` tool, never through native `Skill`-invocation, and
  needs no other engine code — see `engine/staged_skills.py` and
  `engine/staged_skill_tools.py`. Most skills won't need this; it's for
  the minority whose call volume scales with the user's own data.

## v1 Must-Haves

| Skill | Trigger | Input | Output | Notes |
|---|---|---|---|---|
| morning-digest | Daily portfolio/market snapshot | Holdings + index quotes + FII/DII flow + surveillance | Short markdown brief | Generated on-demand only (see vision.md §2) — reminder notifies, this generates |
| portfolio-health-check | Portfolio-wide concentration/winners-losers | Full holdings | Structured review | |
| red-flag-scan | Governance check on one held/watchlist name | One symbol | Flag list w/ severity | |
| thesis-tracker | Define/update/review a thesis on one name | Symbol + user-stated thesis | Per-symbol scorecard, `workspace/theses/<SYMBOL>.md` | Adapted from anthropics/financial-services-plugins via LangAlpha — see `skills/THIRD-PARTY-NOTICES.md` |
| screen-indian-stocks | Candidate ideas from a sector/theme | Sector/theme | Ranked candidate list, `workspace/results/screen_<industry>_<date>.json` | Nifty 500 coverage only |

## Dropped

- **refresh-holdings** — superseded by the manual-trigger decision in
  `vision.md` §2; an interactive session can always complete Kite's login
  itself, so there's no headless-OAuth gap left to work around.

## Writing skill prose (issue #53)

A `SKILL.md` body (everything after the closing `---`) is loaded into the
model's context on every invocation — for a staged skill, once per
top-level turn *and* once per stage (`engine/staged_skills.py`'s
`_build_stage_prompt` prepends the full body to every stage's own
`instructions`), so bloat there is a real, recurring cost, not a one-time
read. Frontmatter `#` comments are the opposite: they never reach the
model at all (a real YAML parser drops them on both the native and staged
load paths — `engine/skills.py`'s `load_skill_body` discards the whole
frontmatter block), so they're free to be as explanatory as helps a human
editing the file.

When writing or editing a step in the body, keep:
- The tool-call sequence, its arguments, and the file paths involved.
- Every status branch and what to do for each — this is the actual
  behavior.
- Output-composition instructions ("Compose the brief" steps) — this text
  *is* the product the user reads; never trim these for length.
- Grounding/safety guardrails ("never compute X by LLM arithmetic," etc).
- A terse "why" only when it changes how the model should weigh a decision
  in the moment.

Move out of the body (a one-line pointer is fine in its place) and into
this skill's design-notes entry below:
- Rationale for *why* an engine mechanism exists — module/function names,
  frontmatter-flag names, issue numbers cited for backstory rather than as
  a pointer.
- "Verified live on `<date>`" evidentiary footnotes — keep the operative
  upshot in the body, move the dated evidence here.
- Migration/history narration already documented elsewhere (cite the doc
  section instead of restating it).
- Boilerplate repeated near-verbatim across multiple skills' bodies —
  tighten to one consistent short form everywhere it appears, since each
  file pays for its own copy independently.

## Design notes

Implementation detail trimmed from skill bodies during the #53 pass —
kept here so the "why" survives for whoever edits these skills next,
without costing the model anything at runtime.

**morning-digest**
- Step 0's account-mismatch bullet used to explain that
  `run_staged_morning-digest` already runs `check_identity_match`
  in-process before stage 1 opens (`identity_precheck: true` in this
  skill's own frontmatter, `engine/skills.py`'s `load_identity_precheck`),
  at zero stage cost, per issue #51. The top-level step-0 check is a
  fail-fast that just reports the same mismatch one tool call sooner in
  the same turn — it isn't a substitute for stage 1's own check, and stage
  1 always re-checks independently regardless.
- Workspace-scoping: an earlier version of this skill was a standing,
  repo-root job (inherited from the old repo's unattended `launchd`
  automation, which needed a fixed path for a notification/script to
  find with no workspace ambiguity). This project has no such pipeline —
  every digest is user-triggered, same as any other skill — so the
  standing-job design no longer applies. Full history:
  `docs/next-phase-plan.md` §4.
- Step 4's index-quote save: the engine's auto-capture recognizes an
  index-only `get_quote` call by its `^`-prefixed tickers, which is how it
  keeps that capture (`data/index_quote_<date>.json`) separate from step
  4b's holdings-quotes capture even though both call
  `india_price.get_quote`.
- Step 4b's live-quotes fetch: why it's needed even though Kite's own
  holdings snapshot already carries `last_price`/`close_price`/
  `day_change_percentage` — those fields can be stale, `india_price` needs
  no Kite session and is always fetched fresh, and `digest_math.py`'s own
  docstring has the full reasoning for anyone tempted to treat this step
  as redundant.
- Step 7's corrupted-capture guardrail: live-observed 2026-08-28 — faced
  with a corrupted ASM/GSM capture, a prior run read fragments of the
  SDK's own raw overflow file and used `Write` to reconstruct a "partial"
  surveillance list with an unverifiable completeness claim. That's why
  the rule is unconditional (never hand-author or patch a capture file,
  report the gap instead) rather than "use judgment."

**portfolio-health-check, thesis-tracker** (and morning-digest, above)
- The account-mismatch paragraph and the "`fetch_holdings`, not
  `kite_gateway.get_holdings`" paragraph both used to carry their full
  backstory in every skill that touches Kite. Full versions, for context:
  a mismatch is unfixable from inside a conversation because the identity
  anchor (`data/account_identity.json`) is engine-managed and write-once
  (`engine/tool_capture.py`) — a human has to delete it by hand to clear a
  stale anchor. `get_holdings` itself is blocked, not just discouraged,
  because a full account's holdings response can exceed the size a raw
  tool result can carry (issue #46) — `fetch_holdings` fetches in-process
  and writes straight to disk specifically to avoid that.
