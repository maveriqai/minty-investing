# Investing Workflow & Skill Roadmap

Companion to `vision.md` and `skills.md`. Where those two answer "what is
Minty" and "what does each skill do," this doc answers a different
question: what's the actual end-to-end process a retail investor goes
through, and does Minty's skill set cover every stage of it? Prompted by a
2026-08-28 session that reviewed `thesis-tracker` against its own real
output, then diffed it against the upstream reference it was adapted from
(`anthropics/financial-services-plugins`, via `ginlix-ai/LangAlpha`'s
re-license of the same content) — see issues #29-#32 for the concrete
findings that came out of that review. This doc is the "does our skill
*set* cover the whole process" follow-up to that skill-by-skill work.

Living document — update it as skills are added, not just when someone
asks "what's the roadmap."

## 1. The three-stage flow

A retail investor's process, as actually described (2026-08-28
conversation): three stages, not a single "research a stock" loop.

1. **Research** — something catches the user's attention: a news
   headline, a tip from someone, or their own generic hunch ("EV companies
   might do well"). Nothing specific yet — no company, maybe not even a
   sector confirmed. The question at this stage: *what's worth looking
   into?*
2. **Thesis** — the user narrows the hunch to a specific set of companies
   and writes down why: the pillars that would make it a good bet, the
   risks that would break it, what it's worth if it plays out. The
   question: *is this specific bet coherent and falsifiable?*
3. **Invest & track** — the user takes a real position (or adds one to a
   watchlist) and wants it monitored going forward — daily moves, new
   filings, whether the pillars are still holding. The question: *has
   anything changed that I need to know about?*

This is a pipeline, not three independent tools — a real session should be
able to move from "I saw something about EVs" to "candidate list" to "one
thesis" to "on my daily digest" without re-explaining context at each
step, the same compounding-across-sessions property `next-phase-plan.md`
§3.1 already identifies as thesis-tracker's core value.

## 2. Stage-by-stage: what Minty has, what the reference implementation has

The comparison target is `anthropics/financial-services-plugins`'
`equity-research` vertical plugin (institutional sell-side framing, but
the skill *granularity* is the useful data point, not the sell-side
tone). LangAlpha's fork of the same plugin is content-identical for every
skill also present in Minty — re-licensed, not redesigned — so "upstream"
below means both at once unless noted.

### Stage 1 — Research

| | Minty today | Upstream |
|---|---|---|
| Theme/sector → candidates | `screen-indian-stocks` (P/E + ROE rank over a named industry) | `idea-generation` ("systematic stock screening... thematic research... triggers on 'what looks interesting', 'pitch me something'") |
| Theme → landscape report | — (nothing) | `sector-overview` (full industry/competitive-landscape report) |

Gap: Minty's entry point to stage 1 requires the user to already have a
named sector or theme in hand. There's no skill for the looser starting
point in the user's own framing above — "I saw a headline," "someone told
me," a vague hunch with no sector attached yet. `idea-generation`'s
trigger list ("what looks interesting," "pitch me something") is aimed
exactly at that looser case. Whether that's worth a dedicated skill or a
broadened `screen-indian-stocks` is an open question, not a decision made
here.

### Stage 2 — Thesis

| | Minty today | Upstream |
|---|---|---|
| Light thesis (user-stated pillars/target, no derived valuation) | `thesis-tracker` | `thesis-tracker` |
| Heavy thesis (derived valuation, institutional report) | — (by design; see thesis-tracker's own "no DCF/comps skill exists yet") | `initiating-coverage` (5-task workflow: company research → financial model → valuation → charts → report) |
| Catalyst tracking | folded into thesis-tracker's own scorecard step, one thesis at a time | `catalyst-calendar` — its **own skill**, scoped across the whole coverage universe, not one thesis file |

Two real findings here, not just a feature-count gap:

- Upstream splits "form a thesis" into two depths on purpose. Minty only
  has the light one, which is consistent with the project's own
  non-negotiables (deterministic math only, no valuation-derivation
  skill yet) — worth stating explicitly as a scoping decision rather than
  an oversight, since it will keep coming up every time thesis-tracker
  gets compared to `initiating-coverage`.
- Upstream's catalyst calendar is portfolio-wide, not per-thesis. Folding
  it into thesis-tracker (as Minty's current `SKILL.md` does — and as the
  2026-08-28 draft rewrite, still un-applied as of this doc, would keep
  doing) means a user with three tracked names has three separate,
  un-cross-referenced catalyst lists instead of one calendar they can
  scan. This is a real design question, not just a wording fix — worth
  weighing before touching thesis-tracker's `SKILL.md` again.

### Stage 3 — Invest & track

| | Minty today | Upstream |
|---|---|---|
| Daily snapshot | `morning-digest` | `morning-note` ("7am morning meeting format — tight, opinionated, actionable") |
| Portfolio-wide health/concentration | `portfolio-health-check` | — (no direct analog) |
| Governance/safety check on one name | `red-flag-scan` | — (no direct analog) |
| Pre-event prep | — (nothing) | `earnings-preview` (bull/bear scenarios, what to watch, before a covered name reports) |
| Post-event deep report | thesis-tracker's "log a data point" step (informal) | `earnings-analysis` (formal 8-12 page report, beat/miss, revised thesis) |
| Model refresh after new data | — (by design, no model-update skill) | `model-update` |

`portfolio-health-check` and `red-flag-scan` have **no upstream analog at
all** — they're Minty-original, and they make sense as originals: an
institutional sell-side vertical doesn't need "am I too concentrated" or
"any governance red flags on this holding" the way a retail investor
directly managing their own book does. Worth keeping in mind when
comparing skill counts: Minty isn't strictly behind upstream stage-3
coverage, it's covering a different, retail-specific slice of the same
stage that upstream doesn't need.

The real gap in stage 3 is the pre-event step. A catalyst can be sitting
on a thesis's calendar (once #31-style tracking exists) with nothing that
actually preps the user before it lands — `earnings-preview`'s "what to
watch for" framing doesn't exist anywhere in Minty today.

## 3. What's already tracked elsewhere

Two of the gaps above were already identified, independently, in
`next-phase-plan.md` §3.4 back when this repo was first scoped:

- **`valuation-screen`** — "nothing today helps go from 'is X undervalued'
  to an answer — screen-indian-stocks discovers candidates, thesis-tracker
  records an already-made decision, nothing sits between them." This is
  exactly the stage-2 "light vs. heavy thesis" gap section 2 identifies
  from a different angle — tracked as issue #10.
- **Morning-digest reading thesis data to nudge on new positions** —
  "watchlist names nearing their stated entry" — a stage-2-to-stage-3
  bridge. Tracked as issue #10's neighbor, issue #12.

Near-term, narrower findings from the 2026-08-28 thesis-tracker review
(not full new skills, fixes to existing ones):

- Issue #29 — morning-digest's materiality dedup
- Issue #30 — portfolio-health-check's missing asset-class breakdown
- Issue #31 — thesis-tracker's pillars have no structural staleness
  tracking (and, per the same day's A/B test, a prose-only fix for the
  related target-price/stop-loss/conviction gaps did not work across 4
  independent test runs — headless and interactive, baseline and a draft
  rewrite. Whatever fixes issue #31 needs to be more structural than
  instruction wording; see the session transcript around 2026-08-28 for
  the full test.)
- Issue #32 — screen-indian-stocks ranks on P/E + ROE only, no growth term

## 4. Candidate skills (not committed, not scoped, not filed)

Surfaced by the stage-by-stage comparison above. Listed here so the gap
is visible next time this doc is read — filing an issue for one of these
is a future decision, not implied by its presence in this list:

- A looser stage-1 discovery skill (or a broadened `screen-indian-stocks`)
  for "I saw a headline" / "someone told me" starting points with no
  sector attached yet — upstream's `idea-generation`.
- A portfolio-wide catalyst calendar, separate from thesis-tracker's own
  per-symbol scorecard — upstream's `catalyst-calendar`.
- A pre-event prep skill for a name already on a thesis or held — "what
  to watch for" before results/an AGM/a regulatory decision lands —
  upstream's `earnings-preview`.
- Macro/market-level research with no symbol and no single sector at all
  — "what's driving FII outflows this month," "is a rate cut coming."
  Distinct from the cross-sector *stock-screening* gap (issue #57):
  `morning-digest` already touches FII/DII flow and index moves as a
  daily snapshot, but nothing persists a compounding, narrative research
  note about macro questions the way `theses/<SYMBOL>.md` or (once built)
  `research/<industry-slug>.md` do for their own subjects. Lighter-weight
  than #57 for now, deliberately not filed as an issue yet — there's no
  producing skill or artifact to point at, only the gap itself. Surfaced
  2026-08-30 alongside issues #56/#57; revisit once something actually
  generates macro-research content worth compounding.

Explicitly not proposing a heavy `initiating-coverage`-style
valuation-derivation skill here — that conflicts with the project's own
deterministic-math non-negotiable unless a real DCF/comps script gets
built first, which is a much bigger decision than this doc should make in
passing.

## 5. How this doc relates to the others

- `vision.md` — the non-negotiables and architecture this doc's proposals
  have to fit inside (deterministic math, grounding, no order execution).
- `skills.md` — once a candidate skill above actually gets scoped, its
  concrete spec (trigger, input, output, grounding rule) belongs in that
  doc's table, not here.
- `next-phase-plan.md` §3.4 — the earlier, narrower version of this same
  gap analysis, written before `thesis-tracker`/`screen-indian-stocks`
  were even ported. Superseded in spirit by this doc for anything
  workflow-shaped; still the right place for the historical
  parity-with-the-old-repo record.
