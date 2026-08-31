# Research Notes — Design Doc (built 2026-08-31, wiring pass)

Fixes issue #40 (split into #58/#59 during the 2026-08-31 issue triage).
Covers engineering mechanics — see `research-notes-experience.md` for the
product/user-experience side first (what changes for the person using
Minty, before any implementation detail). Part of the Stage 1 (Research)
gap named in `investing-workflow-roadmap.md` and tracked by #33:
`thesis-tracker` compounds across sessions for a single symbol
(`theses/<SYMBOL>.md`); nothing played that role for `screen-indian-stocks`'
sector/theme-level output. A real screen ("research investment
opportunities in automotive sector," live-tested 2026-08-28) left behind
only a date-stamped `results/screen_*.json` and an unindexed session
transcript — a repeat query on the same sector had nothing to read back
into.

**Status note (2026-08-31):** this doc was written before
`research-discovery`/`research-discovery-gather` existed
(`docs/research-discovery-plan.md`). That work independently landed the
bucket location this doc's §2.2 originally proposed — split into
`research/sectors|stocks|themes/<key>.md` rather than the flat
`research/<slug>.md` this doc first sketched, and already allow-listed in
`engine/workspace_notes.py`. §2.2 and §2.5 below are updated in place to
match what's actually built; the rest of this doc's reasoning (keying,
content model, merge behavior) still holds and is now shared across four
producers (`research-discovery-gather`, `screen-indian-stocks`,
`red-flag-scan`, `thesis-tracker`'s write-back), not just one.

## 1. Problem, restated precisely

`screen-indian-stocks` already follows the workspace model correctly for
its *computed* output — `results/screen_<industry-slug>_<date>.json`,
independent and never edited after the fact, exactly like every other
skill's results. The gap isn't there. It's that nothing plays
thesis-tracker's *other* role: a small, durable, read-merge-rewrite
document that a later turn on the same subject picks up from, instead of
starting cold. Two screens a week apart on "auto sector" today produce two
unrelated JSON files and nothing that tells the second run what the first
one already found.

## 2. Design decisions

### 2.1 Keying — the industry label, not free-form theme text

The issue's own open question was "sector label? free-form theme? the
screen's own filter?" `screen-indian-stocks` step 2 already answers this
for us: it maps whatever the user says ("undervalued auto sector",
"automotive names") onto one of a fixed set of 19 exact industry labels
from the instruments master, confirming with the user rather than
guessing on a bad match. That mapping already exists and is already
deterministic — reusing it as the research-note key means "auto stocks"
this week and "automotive sector" next week land in the same file without
any new matching logic, because both get funneled through the same step
2 confirmation before either ever reaches a filename.

Concretely: the key is the same `<industry-slug>` already embedded in
`results/screen_<industry-slug>_<date>.json` and
`data/candidates_<industry-slug>_<date>.json` (`_slug()` in both
`list_candidates.py` and `screen_rank.py` — lowercase, non-alphanumeric
runs collapsed to one hyphen, trimmed). The skill should never recompute
this slug itself from scratch — it should reuse the exact filename the
`run_list_candidates`/`run_screen_rank` tool calls already returned this
turn, so there's no chance of the model's own slugification drifting from
the script's.

### 2.1.1 Why the industry label, and not something finer or coarser

One file per industry label — the same "smallest unit the producing skill
already treats as atomic" logic `theses/<SYMBOL>.md` uses (atomic per
symbol because thesis-tracker operates on one symbol per run; atomic per
industry label because `screen-indian-stocks` step 2 already forces every
query onto exactly one of 19 fixed labels before it screens anything).
Checked against the real alternatives, not just asserted:

- **Per-run files** (mirroring `results/screen_*.json`) — already what
  exists today, and exactly what #40 is fixing; a new file every run
  leaves nothing to read back into.
- **One shared `research.md`** for every sector — same reason theses
  don't all live in `notes.md`: cross-subject collision risk, unbounded
  growth, no clean rule for which section a given turn's update belongs
  to.
- **Free-form theme text as the key** — ruled out in §2.1 already: the
  same real subject phrased two different ways would fragment into two
  files, defeating compounding before it starts.

**Honest tradeoff of the label-per-file choice**: it's coarse. A user who
screens autos ten different ways over months — general valuation,
EV-specific, ancillary-parts red flags — gets all of it interleaved in
one `automobile-and-auto-components.md`, not sharply separated by angle.
Left as-is deliberately: splitting further would mean inventing a
sub-theme key that doesn't correspond to anything `screen-indian-stocks`
can actually screen for today. Same "don't build the finer mechanism
until a real file is unwieldy" posture this project already takes
elsewhere (RAG explicitly deferred, `vision.md` §3; thesis staleness
tracking deferred, issue #29) — a trigger to revisit if it happens, not a
speculative build now.

**Real boundary, not a gap in this decision**: a genuinely cross-sector
theme ("PLI-scheme beneficiaries," "rate-cut plays") doesn't map to one
industry label at all — because `screen-indian-stocks` itself can't
screen across sectors in one run, not because the file-keying scheme is
wrong. Same already-named "no sector attached yet" stage-1 gap
(`investing-workflow-roadmap.md` §4's unbuilt `idea-generation`-style
skill) — out of scope here, and would need its own keying decision if it
ever gets built.

### 2.2 Location — `workspace/research/sectors/<industry-slug>.md`

Parallel to `workspace/theses/<SYMBOL>.md`, for the same reason: this is
the one other case where a skill's output is a living, per-key document
rather than a flat, independent, date-stamped result. `docs/vision.md` §4
already names `theses/<SYMBOL>.md` as "the one exception to flat" —
`research/sectors/<slug>.md` is a second instance of that same exception,
not a new category of exception.

**Updated 2026-08-31:** as actually built (via `research-discovery-plan.md`,
independently of this doc), the bucket is split three ways by subject
shape rather than being one flat `research/<slug>.md`:
`research/sectors/<industry-slug>.md` (this section's original target —
`screen-indian-stocks`' own output), `research/stocks/<SYMBOL>.md` (a
single-symbol subject — `red-flag-scan`'s output, and the target §2.5's
research→thesis bridge actually reads/writes), and
`research/themes/<slug>.md` (a cross-cutting subject that doesn't reduce
to one sector or stock). All three are allow-listed in
`engine/workspace_notes.py`'s `_resolve_target`. The keying logic in §2.1
above is unchanged — it's still "reuse the deterministic slug the
producing skill already computed" — only the directory a given key lands
in changed, by subject shape.

### 2.3 Content model

```markdown
# Research Note — <Industry Label>

## Screen History
| Date | Candidates | Top 5 (P/E · ROE · source) | Results file |
|---|---|---|---|
| 2026-08-28 | 25 | RELIANCE (12.3 · 14.1% · screener.in), ... | results/screen_automobile-and-auto-components_2026-08-28.json |

## Observations
- 2026-08-28: <durable qualitative note — sector-wide theme, a name to
  revisit, a red flag surfaced during step 6's optional annotation>
```

Two sections, both append-only:

- **Screen History** is an index, not a copy of the data — it links to
  the actual `results/screen_*.json` for that date rather than
  re-embedding the full ranked/excluded lists. Same "cite, don't
  re-derive" principle `notes.md` already follows: the numbers stay
  computed-once in the results file; the note just makes past runs
  discoverable.
- **Observations** is where anything genuinely durable and qualitative
  goes — a sector-wide pattern noticed across two screens, a name worth a
  closer look next time, a red flag from step 6's optional
  red-flag-annotation of the top 5. Dated bullets, oldest first, never
  rewritten — same convention as thesis-tracker's own scorecard log.

**Updated 2026-08-31:** these two sections aren't the whole file anymore —
`research-discovery-gather`'s `synthesize` stage also writes into these
same bucket files, under its own `## Findings` heading (a dated narrative
entry per gather run), and `red-flag-scan` writes a parallel `##
Red-Flag Checks` table into the `research/stocks/` bucket (same shape as
this section's `## Screen History`, just keyed by symbol instead of
sector). All four producers share one `## Observations` section and the
same rule: read the file first, append under your own heading, never
touch or rewrite a section you don't own.

No new deterministic script. Appending a Screen History row is
transcription from an already-computed JSON file, not money-math — the
same category of step thesis-tracker's own scorecard update (step 5)
already does in prose, with no dedicated script. If cross-screen drift
tracking (e.g. "median P/E for this sector compressed 8% since the last
screen") turns out to be a real, repeated want, that's a follow-up in the
same spirit as issue #29 (thesis-tracker's own still-unbuilt staleness
tracking) — not something to build speculatively now.

### 2.4 Merge behavior

Identical shape to thesis-tracker step 5: `Read` the file first (it may
not exist), merge the new dated entry into both sections, then call
`update_workspace_notes` with the full merged content. Never overwrite.
Because the key is the canonical industry label (§2.1), this merge always
lands on the same file regardless of how the user phrased the query
either time — the thing the issue asked "how does a repeat query merge
rather than overwrite" actually reduces to "give it a stable key," which
step 2's existing confirmation already guarantees.

### 2.5 The research → thesis bridge

The three-stage flow in `investing-workflow-roadmap.md` §1 (Research →
Thesis → Invest & Track) is explicit that this is meant to be one
pipeline, not three tools that don't talk to each other. A research note
that only ever gets appended to and never read by anything downstream
stops short of that — the actual payoff is a name that shows up well
across two or three screens becoming an easy, well-informed "track a
thesis on this" moment, not a fact the user has to remember and restate
themselves.

Two linked, one-directional writes, kept deliberately asymmetric so
neither skill's `SKILL.md` is doing the other's job:

- **thesis-tracker reads `research/stocks/<SYMBOL>.md` when a *new*
  thesis is opened** (its step 2, new-thesis path only — an update to an
  existing thesis has no reason to re-check). Before asking the user for
  pillars/risks/target: `Read` `research/stocks/<SYMBOL>.md` — exact key,
  no `Glob`/search needed (unlike `research-discovery`'s own step 2,
  which scans whole subdirectories because it doesn't yet have one
  specific symbol to key on; thesis-tracker always does). If found, cite
  what's already there as a starting point in the prompt back to the
  user — red-flag history, any `research-discovery` `## Findings`, prior
  `## Observations` — clearly labeled as "from your research note on
  `<SYMBOL>`, dated `<date>`," never silently folded into the thesis as
  if newly derived. **The user still states the pillars, risks, target
  price, and stop-loss themselves** — this is citation of already-gathered
  facts, not thesis-tracker deriving anything, so it doesn't touch the
  "target price is the user's stated input, not this skill's output"
  guardrail at all.
- **thesis-tracker writes one line back to that same file**, in step 5,
  once the new thesis is actually opened: append to its `##
  Observations`, e.g. "2026-09-01: started a thesis on TATAMOTORS, see
  `theses/TATAMOTORS.md`." Uses the same already-allow-listed
  `research/stocks/<SYMBOL>.md` target — no new engine mechanism, since
  `update_workspace_notes`' allow-list is keyed on the target path
  pattern, not on which skill is calling it. This is what makes the
  research note's own history genuinely useful later: opening it shows
  which candidates converted into a real tracked thesis and which didn't,
  not just a list of names that were once flagged or ranked well.

**Updated 2026-08-31:** originally keyed on the (now superseded) flat
`research/<industry-slug>.md`, since a symbol's only research trail was a
sector screen. Now that `research/stocks/<SYMBOL>.md` exists as its own
bucket (§2.2), the bridge targets that instead — a tighter, symbol-exact
key than the sector file, and the same file `red-flag-scan` (#59) and a
single-symbol `research-discovery` run both already write into. A symbol
that only ever showed up in a *sector* screen (`research/sectors/`, never
individually red-flag-checked or discovery-researched) has no
`research/stocks/<SYMBOL>.md` yet, so thesis-tracker's lookup finds
nothing for it — a real, accepted gap (see the out-of-scope note on
sector→stock cross-pollination in `docs/skills.md`'s design notes for
`screen-indian-stocks`/`red-flag-scan`), not a bug in this bridge.

No change to `screen-indian-stocks` for this part — the bridge lives
entirely in `thesis-tracker`'s own new-thesis path, since that's the only
point where "the user is committing to one name" actually happens.

**Explicitly not built here**: a proactive nudge ("this name ranked
top-5 across your last 3 screens — want to track it?"). That's the same
shape as issue #12 (nudge on thesis-less positions nearing entry), one
stage earlier in the pipeline — worth its own issue once this bridge
exists to nudge from, not something to bundle into #40's implementation.

## 3. Mechanical changes (as actually implemented, 2026-08-31)

- **`engine/workspace_notes.py`** — the allow-list extension this section
  originally specified was built already, but with the sectors/stocks/
  themes split (§2.2) instead of one flat pattern:
  `_SECTOR_RESEARCH_RE`, `_STOCK_RESEARCH_RE`, `_THEME_RESEARCH_RE` (plus
  `_RESEARCH_PLAN_RE` for `research-discovery`'s own plan-file handoff,
  unrelated to this doc). Landed as part of `docs/research-discovery-plan.md`,
  not this doc — see that plan's §6 for the actual mechanics. No further
  engine change needed for #58/#59/thesis-tracker's bridge; every target
  path this section's producers write is already allow-listed.

- **`.claude/skills/screen-indian-stocks/SKILL.md`** (issue #58) — a new
  step 3 (before building the candidate universe) reads
  `research/sectors/<industry-slug>.md` and leads with anything relevant;
  a new step 10 (after composing the brief) merges a `## Screen History`
  row and an `## Observations` bullet into that same file via
  `update_workspace_notes`, reusing the slug from step 4/6's own output
  filenames rather than recomputing it (§2.1). No `expected_outputs`
  change — this file is a manually-merged bucket note, not an
  engine-auto-composed artifact, same reasoning `research-discovery-gather`
  already established for its own `expected_outputs: []`.

- **`.claude/skills/red-flag-scan/SKILL.md`** (issue #59) — same shape: a
  new step 3 reads `research/stocks/<SYMBOL>.md` before pulling the six
  inputs; a new step 7 (after composing the brief) merges a `##
  Red-Flag Checks` row and an `## Observations` bullet into it. This
  section originally said "no changes needed" to red-flag-scan, on the
  assumption its only research-note presence would be as a byproduct of
  `screen-indian-stocks`' own step 6/7 top-5 annotation — but that never
  gave a *direct* `red-flag-scan` run (the common case — "any red flags on
  X" outside a screen) anywhere durable to write to. #59 fixes that gap
  directly instead.

- **`.claude/skills/thesis-tracker/SKILL.md`** — in step 2's new-thesis
  path only, the research-note lookup and citation described in §2.5; in
  step 5, the single `## Observations` line written back via a second
  `update_workspace_notes` call, `target=research/stocks/<SYMBOL>.md`,
  once the thesis is opened. No frontmatter changes (no new deterministic
  script, no new tool).

## 4. Explicitly out of scope for this pass

- The stage-1 "no sector attached yet" discovery gap — filled separately
  by `research-discovery`/`research-discovery-gather`
  (`docs/research-discovery-plan.md`), not this doc.
- Numeric staleness/drift tracking across screens — see §2.3.
- `screen-indian-stocks`' step 7 (optional top-5 red-flag annotation)
  *also* seeding `research/stocks/<SYMBOL>.md` for each flagged name, so a
  later direct `red-flag-scan` run on that name inherits the context —
  real cross-pollination value, genuinely deferred rather than folded into
  #58/#59: it's up to 5 extra `update_workspace_notes` calls per screen,
  and a separate question of how it'd collide with #58's own sector-bucket
  write for the same names. Worth its own follow-up once the core loop
  (this doc) is live and the value is felt in practice, not built
  speculatively now.
- A proactive "this name keeps ranking well — want a thesis?" nudge —
  see §2.5's closing note; the bridge here is read/cite-on-request, not
  push.

## 5. Testing plan

- `tests/test_engine_workspace_notes.py` — already covers `_resolve_target`
  for `research/sectors|stocks|themes/<key>.md` (built with
  `research-discovery-plan.md`'s implementation); no engine-level test gap
  remains for this doc's own producers, since they write through the same
  already-tested tool/allow-list.
- Live verification: run `screen-indian-stocks` twice against the same
  industry (different phrasing each time — e.g. "cheap auto names" then
  "automotive sector check") a session apart, confirm both land in one
  `research/sectors/automobile-and-auto-components.md` with two Screen
  History rows, not two separate files. Same for `red-flag-scan` twice on
  the same symbol, confirming one `research/stocks/<SYMBOL>.md` with two
  Red-Flag Checks rows. Same live-verification bar thesis-tracker and
  staged execution were held to before being marked built.
- Coexistence verification: run `research-discovery` on a subject that
  resolves to a sector already screened (or a symbol already red-flag-
  scanned), confirm `synthesize` merges its `## Findings` entry into the
  existing file without disturbing the `## Screen History`/`##
  Red-Flag Checks`/`## Observations` sections already there, and vice
  versa (run the screen/scan after a research-discovery pass already
  populated the file).
- Bridge verification: after a screen or scan creates a
  `research/stocks/<SYMBOL>.md` note, open a new thesis on that symbol and
  confirm (a) the thesis-creation prompt cites the research note's
  figures with source/date rather than re-deriving or silently
  re-fetching, and (b) the research note gains exactly one new
  Observations line pointing at the new thesis file — run it a second
  time on an unrelated symbol never seen in any research note and confirm
  no citation and no spurious write happen.
