# Research Notes — Product & User Experience (built 2026-08-31, wiring pass)

Fixes issue #40 (superseded by #58/#59, both closed). Companion to
`research-notes-design.md`, which covers the engineering mechanics
(allow-listed write target, file format, testing) and now reflects what
actually shipped. This doc starts from the other end: what actually
changes for the person using Minty, before any implementation detail.

**Status note (2026-08-31):** the product shape described below shipped —
`screen-indian-stocks` and `red-flag-scan` both check for and merge into a
durable research note, and the thesis hand-off in §5 is built. Two details
in the original proposal changed on the way to real code, both explained
where they come up: the note lives at `research/sectors/<slug>.md` /
`research/stocks/<SYMBOL>.md` (a key-scoped split, not the single flat
`research/<slug>.md` path §3's example uses — see
`research-notes-design.md` §2.2), and §7 landed on the "narrated delta"
side but as a lighter prose callback, not the deterministic diff table
§3's example implies — see the note at §7.

## 1. The gap, from the user's seat

A user runs `screen-indian-stocks` on the auto sector on Aug 28, reads a
ranked list, closes the session. Two weeks later they ask "anything new in
auto stocks?" — today, Minty starts over completely: same universe pull,
same fundamentals fetch, zero memory that the earlier screen ever
happened. The only way the user gets a comparison is remembering the
earlier numbers themselves, or knowing to go dig through a raw session
transcript they likely don't know exists. For a tool pitched as
"Obsidian for investing" — notes that compound across sessions — this is
the one place that pitch quietly doesn't hold: `thesis-tracker` delivers
on it for a single stock, and sector-level research doesn't.

## 2. What changes for the user

**Nothing to learn.** Same trigger phrases work exactly as they do today
("find undervalued auto sector stocks," "any updates on autos") —
`screen-indian-stocks` still owns this, no new command, no new decision
the user has to make.

**A first screen on a subject looks almost identical to today.** The
ranked list comes back the same way; the only addition is knowing it's
been saved for next time.

**A repeat screen on a subject already researched is where the value
shows up.** The reply opens with a short callback before the fresh
ranking, instead of presenting a cold list the user has to compare
against memory themselves:

> Last looked at Automobile and Auto Components on 2026-08-28 (25
> candidates). Since then: TATAMOTORS moved from #4 to #1 (P/E compressed
> 18.0 → 14.2), BAJAJ-AUTO dropped off the ranked list (ROE data now
> missing), 2 names are new to the universe. Full ranking below.

That one-liner is the actual product payoff — orientation in one
sentence, instead of re-reading an entire new list cold and trying to
recall what it looked like last time. This is a genuine, not-yet-decided
scope question — see §6.

## 3. What the user can go read directly

`workspace/research/sectors/<slug>.md` (as shipped — see the status note
above; the example below still shows the originally-proposed flat path) —
a plain markdown file, openable in
Obsidian or any editor, the same way `theses/RELIANCE.md` already is
today. Roughly:

```markdown
# Research Note — Automobile and Auto Components

## Screen History
| Date | Candidates | Top 5 (P/E · ROE · source) | Results file |
|---|---|---|---|
| 2026-08-28 | 25 | TATAMOTORS (14.2 · 16.8% · screener.in), ... | results/screen_automobile-and-auto-components_2026-08-28.json |
| 2026-08-14 | 25 | RELIANCE... | results/screen_automobile-and-auto-components_2026-08-14.json |

## Observations
- 2026-08-28: TATAMOTORS' re-rating tracks the EV-launch news cycle —
  worth a thesis if the next quarter holds up.
- 2026-08-14: BAJAJ-AUTO flagged high promoter pledge in step 6's
  red-flag pass; watch before adding.
```

It's meant to be skimmed by a person, not just consumed inside a chat
turn — the whole point of the workspace being real files on disk is that
the user's research compounds somewhere they can browse it themselves,
not only somewhere Minty can retrieve it for them.

## 4. What this doesn't do — setting expectations

- **Doesn't replace `thesis-tracker`, but does hand off to it.** A
  research note stays sector/theme-scoped, and committing to one name is
  still its own deliberate step — nothing here starts a thesis on the
  user's behalf. What changes is that step gets easier: see §5.
- **Doesn't change the numbers.** `results/screen_*.json` stays the
  source of truth for any figure; the note only narrates change over
  time and links back to the file, never recomputes or restates a number
  as if the note itself were authoritative.
- **Doesn't ask the user to manage it.** No "start a new research note"
  step, no naming decision — same "engine decides where, model decides
  what" property `notes.md` and `theses/<SYMBOL>.md` already have.

## 5. The bridge to a thesis

Research is only step one of the flow described in
`investing-workflow-roadmap.md` — Research → Thesis → Invest & Track. A
note that only ever accumulates and never gets used stops short of that.
Two small, concrete changes at the exact moment the user decides to act
on something they found:

**Starting a thesis on a name already seen in research gets a head
start.** The user says "track a thesis on TATAMOTORS" after having
screened autos twice. Instead of thesis-tracker asking cold for
everything, it opens with what's already known:

> Found TATAMOTORS in your Automobile and Auto Components research
> (last screened 2026-08-28): ranked #1, P/E 14.2, ROE 16.8%
> (screener.in). Flagged red-flag-clean in that screen's step 6 check.
> Want to use these as your starting pillars, or start fresh?

The user still writes the actual thesis — pillars, risks, target,
stop-loss — themselves. Nothing here is Minty deciding the bet is good;
it's Minty not making the user re-type numbers it already fetched three
weeks ago.

**Opening a thesis closes the loop on the research note it came from.**
The research note that surfaced TATAMOTORS gets one line added to its
Observations — "started a thesis on TATAMOTORS, see
`theses/TATAMOTORS.md`." The next time the user opens that sector's
research note (or the next time a screen on that sector triggers the
"since last time" callback from §2), it's visible which candidates
actually became real tracked positions and which were just names that
once ranked well and were never revisited. That's the difference between
a research note being a log and being a working part of the pipeline.

**What this deliberately isn't**: a proactive push — "TATAMOTORS ranked
top-5 three screens running, want to start a thesis?" unprompted. That's
a related, real idea (the same shape as issue #12's nudge on
thesis-less positions, one stage earlier), but a different scope
decision — surfacing context when the user asks is a much smaller trust
step than Minty initiating the suggestion itself.

## 6. Edge cases, from the user's perspective

- **Different phrasing, same sector.** "Cheap auto names" today, "check
  on automotive" next week — both go through the existing sector-mapping
  confirmation, both land on one file. No duplicate notes, no visible
  seam, nothing the user has to reconcile.
- **First-ever screen on a subject.** No callback, since there's nothing
  to compare against — just the ranked list, same as today, plus the
  note now existing for next time.
- **A genuinely different subject the user treats as related but Minty's
  fixed label set doesn't.** E.g. asking about "EV names" where the
  mapping lands on a different label than "auto sector" did before —
  two separate files, two separate histories. Same behavior as two
  distinct stocks never sharing a thesis file; not a bug, just a
  reminder that the key is the confirmed label, not the user's own
  mental grouping.

## 7. Open product question — how much comparison is automatic

Two honest options, not yet decided:

- **Minimal**: the note is written and updated silently every screen;
  nothing changes about what the user is told in the reply itself. Lower
  risk (no new narrated claim to get wrong), but most of the
  "compounding" value stays invisible unless the user thinks to open the
  file themselves.
- **Narrated delta** (the callback in §2): the model reads the prior
  note before composing the reply and calls out what changed. Delivers
  the actual point of this feature, but the callback itself would be
  prose comparison over two already-computed JSON files, not a
  deterministic diff — the same category of judgment call
  `thesis-tracker`'s still-open staleness-tracking gap (issue #29) lives
  in. Worth deciding deliberately rather than drifting into either
  option.

Recommendation: ship the narrated delta, since a silently-written file
nobody is told about doesn't actually fix the problem #40 describes — but
flag explicitly (in the reply itself, if the comparison looks
inconsistent — e.g. a candidate's rank moved but its underlying P/E
didn't, which would mean a peer's number changed instead) rather than
asserting a clean story when the underlying data doesn't cleanly support
one.

**As shipped (2026-08-31):** landed on the narrated-delta side of this
question, but lighter than the full computed diff table sketched above —
`screen-indian-stocks` step 3 and `red-flag-scan` step 3 read the prior
note and lead the reply with whatever's still relevant ("your last screen
on this sector, three weeks ago, flagged...") rather than computing a
structured rank/P/E delta. Same spirit (context over cold start), smaller
surface for the model to get wrong — a deterministic diff table remains a
reasonable future upgrade if the prose version proves insufficient.
