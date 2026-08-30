# Research Notes — Design Doc (proposed, not yet implemented)

Fixes issue #40. Covers engineering mechanics — see
`research-notes-experience.md` for the product/user-experience side first
(what changes for the person using Minty, before any implementation
detail). Part of the Stage 1 (Research) gap named in
`investing-workflow-roadmap.md` and tracked by #33: `thesis-tracker`
compounds across sessions for a single symbol (`theses/<SYMBOL>.md`);
nothing plays that role for `screen-indian-stocks`' sector/theme-level
output. A real screen ("research investment opportunities in automotive
sector," live-tested 2026-08-28) leaves behind only a date-stamped
`results/screen_*.json` and an unindexed session transcript — a repeat
query on the same sector has nothing to read back into.

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

### 2.2 Location — `workspace/research/<industry-slug>.md`

Parallel to `workspace/theses/<SYMBOL>.md`, for the same reason: this is
the one other case where a skill's output is a living, per-key document
rather than a flat, independent, date-stamped result. `docs/vision.md` §4
already names `theses/<SYMBOL>.md` as "the one exception to flat" —
`research/<slug>.md` is a second instance of that same exception, not a
new category of exception.

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

- **thesis-tracker reads research notes when a *new* thesis is opened**
  (its step 2, new-thesis path only — an update to an existing thesis has
  no reason to re-check). Before asking the user for pillars/risks/
  target, search `workspace/research/*.md` for the symbol (a handful of
  files, each small — a plain `Read`/`Grep` pass, no new tool, no
  meaningful cost). If found, cite what's already there as a starting
  point in the prompt back to the user — rank history, P/E/ROE with
  source, any Observations already logged for that name — clearly
  labeled as "from your research note on `<industry>`, dated `<date>`,"
  never silently folded into the thesis as if newly derived. **The user
  still states the pillars, risks, target price, and stop-loss
  themselves** — this is citation of already-gathered facts, not
  thesis-tracker deriving anything, so it doesn't touch the "target price
  is the user's stated input, not this skill's output" guardrail at all.
- **thesis-tracker writes one line back to the research note that
  surfaced the name**, in the same step, once the new thesis is actually
  opened: append to that file's Observations, e.g. "2026-09-01: started a
  thesis on TATAMOTORS, see `theses/TATAMOTORS.md`." Uses the same
  already-allow-listed `research/<slug>.md` target — no new engine
  mechanism, since `update_workspace_notes`' allow-list is keyed on the
  target path pattern, not on which skill is calling it. This is what
  makes the research note's own history genuinely useful later: opening
  it shows which candidates converted into a real tracked thesis and
  which didn't, not just a list of names that were once ranked well.

No change to `screen-indian-stocks` for this part — the bridge lives
entirely in `thesis-tracker`'s own new-thesis path, since that's the only
point where "the user is committing to one name" actually happens.

**Explicitly not built here**: a proactive nudge ("this name ranked
top-5 across your last 3 screens — want to track it?"). That's the same
shape as issue #12 (nudge on thesis-less positions nearing entry), one
stage earlier in the pipeline — worth its own issue once this bridge
exists to nudge from, not something to bundle into #40's implementation.

## 3. Mechanical changes

- **`engine/workspace_notes.py`** — extend the allow-list. Currently
  `_resolve_target` accepts `"notes.md"` or `theses/<SYMBOL>.md`
  (`_THESIS_TARGET_RE`). Add:

  ```python
  _RESEARCH_TARGET_RE = re.compile(r"^research/[a-z0-9]+(-[a-z0-9]+)*\.md$")
  ```

  matching the exact `_slug()` output shape (lowercase, single hyphens,
  no leading/trailing hyphen). Update `_resolve_target` to check it, and
  update `_TARGET_DESCRIPTION` / the tool's registered description string
  to document the third accepted shape, same pattern as the existing
  thesis-file documentation. Still a small, fixed set the model chooses
  *from* — no arbitrary path.

- **`.claude/skills/screen-indian-stocks/SKILL.md`** — add a step after
  the current step 8 (compose the brief): read `research/<slug>.md` via
  `Read` (may not exist yet), merge in this run's Screen History row plus
  any Observations worth keeping (including anything from step 6's
  optional red-flag annotation), then call `update_workspace_notes` with
  `target` set to `research/<slug>.md`. Explicitly reuse the slug from
  step 3/5's own output filename rather than recomputing it (§2.1). Add
  `"{workspace}/research/*.md"` to the frontmatter's `expected_outputs`.

- **`.claude/skills/thesis-tracker/SKILL.md`** — in step 2's new-thesis
  path only, add the research-note lookup and citation described in
  §2.5, and the single Observations line written back via
  `update_workspace_notes` with `target=research/<slug>.md` once the
  thesis is opened. No frontmatter changes needed (no new deterministic
  script, no new tool).

- **No changes needed** to `red-flag-scan` or any other skill. Red-flag
  findings that surface during screen-indian-stocks' own step 6 land in
  the research note as a byproduct of that screen's Observations — not a
  second write path from red-flag-scan itself.

## 4. Explicitly out of scope for this pass

- The stage-1 "no sector attached yet" discovery gap
  (`investing-workflow-roadmap.md` §4's candidate `idea-generation`-style
  skill) — unrelated: this only fixes compounding for
  `screen-indian-stocks`' existing entry point, not the entry point
  itself.
- Numeric staleness/drift tracking across screens — see §2.3.
- Folding red-flag-scan's own single-symbol runs (outside a screen) into
  this file — a symbol the user commits to belongs in thesis-tracker, not
  here; a research note stays sector/theme-scoped.
- A proactive "this name keeps ranking well — want a thesis?" nudge —
  see §2.5's closing note; the bridge here is read/cite-on-request, not
  push.

## 5. Testing plan

- `tests/test_engine_workspace_notes.py` — extend with the same shape of
  cases already there for `theses/<SYMBOL>.md`: `_resolve_target` accepts
  `research/automobile-and-auto-components.md`, rejects uppercase,
  rejects a bad extension, rejects `../escape.md`-style traversal through
  the new prefix; a tool-level test that a first call creates
  `workspace/research/<slug>.md` and a second call with merged content
  overwrites-with-merge (mirrors
  `test_update_workspace_notes_tool_writes_to_a_thesis_file` /
  `_overwrites_with_merged_content`).
- Live verification once implemented: run `screen-indian-stocks` twice
  against the same industry (different phrasing each time — e.g. "cheap
  auto names" then "automotive sector check") a session apart, confirm
  both land in one `research/automobile-and-auto-components.md` with two
  Screen History rows, not two separate files. Same live-verification bar
  thesis-tracker and staged execution were held to before being marked
  built.
- Bridge verification: after a screen creates a research note, open a new
  thesis on one of its candidates and confirm (a) the thesis-creation
  prompt cites the research note's figures with source/date rather than
  re-deriving or silently re-fetching, and (b) the research note gains
  exactly one new Observations line pointing at the new thesis file — run
  it a second time on an unrelated symbol never seen in any research note
  and confirm no citation and no spurious write happen.
