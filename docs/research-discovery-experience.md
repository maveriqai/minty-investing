# Research Discovery — Product & User Experience (built 2026-08-31)

Captures the shape of an idea, not a committed feature — written to sharpen
and preserve the thinking before any design or implementation decision.
This is the fuller specification of the gap named in three places already
(`next-phase-plan.md` §3.4, `investing-workflow-roadmap.md` §4's
`idea-generation` bullet, issue #57), and it reframes how #40/#56/#57's
research-note buckets get used — see §8. Companion in spirit to
`research-notes-experience.md`, same "product experience first" approach,
for a bigger and less settled idea.

**Status note (2026-08-31):** shipped as the `research-discovery` +
`research-discovery-gather` skill pair (`b6ddc90`) — the scoping-question
rule in §4 (fire only when two reasonable interpretations would lead to
meaningfully different work) and its own worked examples are implemented
close to verbatim in `research-discovery`'s `SKILL.md` steps. See
`research-discovery-plan.md` for the engineering shape (two skills, not
one — a staged run can't pause mid-way to ask the user anything) and
`research-discovery-architecture.md` for why that split was chosen.

## 1. The moment this is for

Every research skill today needs the user to already know the shape of
what they want: a sector (`screen-indian-stocks`), a symbol
(`red-flag-scan`, `thesis-tracker`). Real research doesn't start there.
It starts as:

- "Just read that the PLI scheme for semiconductors got a new funding
  tranche — might be worth a look."
- "A friend said to check out XYZ, no idea if it's any good."
- "Should I be worried about my auto holdings given the rupee's been
  sliding?"
- "What's actually driving the market down this week?"

None of these name a sector or a symbol cleanly. Today, the user has to
do the translation work themselves — figure out which skill applies, phrase
it in a way that skill's trigger recognizes, and if it doesn't fit any
existing shape, there's simply nothing to ask. The gap isn't "which skill
handles this" — it's that the *first* step of real research, figuring out
what's even worth looking at, isn't something Minty does at all yet.

## 2. What happens today, concretely

Ask Minty "should I be worried about my auto holdings given the rupee"
right now, and best case it makes a reasonable ad hoc guess about which
tool to call once, with no plan, no check of what's already known, and no
structured way to tell the user what it did or didn't cover. There's no
step that says "here's what I'm going to look at, in this order, tell me
if that's not what you meant" — the user finds out what Minty actually
did only by reading the answer it already gave.

## 3. What the new experience feels like

A concrete walkthrough, start to finish:

> **User:** Just read that India's PLI scheme for semiconductors got a
> big new funding tranche. Might be worth a look.
>
> **Minty:** A few ways I could take this — want me to focus on pure-play
> semiconductor names, or also cast a wider net to component/materials
> suppliers that'd benefit indirectly? And are you thinking near-term
> trade or a longer research thread?
>
> **User:** Pure-play names, just curious for now, not urgent.
>
> **Minty:** Checked your workspace — no prior research on this. Here's
> what I found:
>
> **Policy context** (india_news, 3 articles, 2026-08-29–30): the
> tranche adds ₹XX,XXX cr to the existing scheme, targeting fab and
> ATMP capacity...
>
> **Company-level candidates**: Minty's screening tools group by the
> instruments master's industry labels, and there's no "semiconductor"
> label in that set — the closest listed names sit under Information
> Technology or Capital Goods depending on what they actually make.
> I couldn't find an authoritative list of PLI beneficiaries specifically
> — the names below are just NSE-listed companies with semiconductor
> exposure I could identify from recent filings/news, not a confirmed
> beneficiary list. Treat this as a starting point, not a screen result.
>
> [...found names, each with what's actually known about them...]
>
> Saved what I found to a new research note — ask about this again
> anytime and I'll pick up from here instead of starting over.
>
> Next: Want me to go deeper on any of these names, or check whether any
> are already something you hold?

Three things happening there worth naming explicitly: the scoping
question up front (§4), the workspace check before doing any fresh work,
and — critically — the tool being upfront about exactly where its own
data runs out, rather than presenting a clean answer it can't actually
back up.

## 4. The scoping question — when it fires, and when it doesn't

This only matters if it's used sparingly. Nobody wants an interrogation
before every question. The rule that keeps it from becoming annoying:
**ask only when the ask is genuinely underspecified in a way that would
change what gets looked up** — not as a default courtesy step.

- **"Screen auto sector stocks"** — already crisp. No scoping question;
  goes straight to `screen-indian-stocks` exactly as it does today. This
  flow doesn't touch that path at all.
- **"Someone told me to check out XYZ"** — already a symbol. Goes to a
  single-stock path (`red-flag-scan`, which now also checks and updates
  `research/stocks/<SYMBOL>.md` itself — #56/#59, closed), not this one —
  no multi-angle reasoning needed for something this specific.
- **"PLI semiconductor tranche"** — genuinely ambiguous (pure-play vs.
  broader supply chain, quick curiosity vs. building toward a position) in
  a way that changes real work about to happen. One question, not five.
- **"What's driving the market down this week"** — arguably doesn't even
  need a scoping question, since there's only one reasonable
  interpretation; this should just run and gather (news, FII/DII flow,
  whatever's relevant), no interrogation for its own sake.

The test isn't "is this vague" — it's "would two different reasonable
interpretations lead to meaningfully different work." If not, don't ask.

## 5. How this sits alongside the fast, already-shaped skills

Nothing about the five existing skills changes. If the user already knows
what they want and says it plainly, it should feel exactly as fast as it
does today — no added scoping step, no detour through a heavier reasoning
process for a request that was never ambiguous. This is specifically the
front door for the moment the user *doesn't* know the shape yet; it's not
a new mandatory layer in front of everything else. A user who always says
"screen the FMCG sector" should never notice this exists.

## 6. What "coherent" actually means, not just "collected"

The failure mode to avoid: five separate tool results concatenated with
headers, leaving the user to synthesize it themselves — which is exactly
what happens today if the model makes several ad hoc tool calls without a
skill's structure to organize them. "Coherent" means: organized by angle
(policy/macro context, company-level findings, portfolio relevance if
any), each claim visibly sourced (which tool, which date), and an explicit
account of what *wasn't* found or couldn't be confirmed — not folded
quietly into the confident parts of the answer, but called out as its own
line, the way the PLI example above does for "no confirmed beneficiary
list exists."

## 7. Being honest about gaps is the actual trust-critical part

This is worth stating as a first-class product requirement, not a
technical footnote: open-ended research is exactly the situation where an
LLM is most tempted to fill in plausible-sounding background from its own
training instead of a live source — this is precisely the failure mode
"grounding" (`docs/vision.md` §5) exists to prevent everywhere else in
this product, and it gets harder to hold the line on the more open-ended a
request is. The user should be able to trust that if Minty says something,
it came from a real tool call this turn or an existing workspace file —
and if Minty *can't* find something, it says so plainly rather than
quietly smoothing over the gap. A user who catches this tool making up
even one unsourced claim stops trusting every other answer it gives,
including the ones that were fully grounded.

## 8. How this connects to the compounding work already designed

This doesn't replace `research/sectors/<slug>.md` (#40),
`research/stocks/<SYMBOL>.md` (#56), or `research/themes/<slug>.md` (#57)
— it's the thing that decides *which* of those a given research pass
actually belongs in, once the shape becomes clear, and can write into more
than one if a research pass genuinely spans angles (a PLI-semiconductor
pass might touch both a `themes/` file and, for any name the user already
holds, a portfolio-relevance note). The buckets stay as the compounding
memory; this is what feeds them from an unshaped starting point instead of
requiring the user to already know which bucket to aim at.

The payoff compounds the same way as everywhere else in this product: ask
about the same thing again next month, and Minty opens with what it
already found instead of starting cold — the workspace-check step in §3
is what makes that automatic rather than something the user has to
remember to ask for.

## 9. What this doesn't do

- **Doesn't derive investment advice or a conclusion.** Same boundary
  every other skill holds — this narrates data and organizes it by angle;
  it never tells the user what to do. The SEBI disclaimer applies the same
  way it does everywhere else.
- **Doesn't guess a fact it can't source.** See §7 — the honest gap is
  the point, not a bug to hide.
- **Doesn't ask more than one clarifying question per genuinely ambiguous
  request.** If the first answer doesn't fully resolve scope, better to
  proceed on a reasonable interpretation and say what interpretation was
  used than to keep interrogating.
- **Doesn't slow down or complicate a request that was already clear.**
  See §5.

## 10. Edge cases, from the user's seat

- **The ask is already well-covered in the workspace.** Minty should lead
  with that ("You already have a research note on this from three weeks
  ago — here's what's changed since") rather than silently re-running
  everything from scratch.
- **Minty genuinely has no data source for part of the ask** (e.g. "what
  are options traders positioning for" — nothing in Minty's tool set
  covers derivatives sentiment). Says so plainly for that piece, and still
  delivers whatever adjacent pieces it *can* actually source, rather than
  refusing the whole request.
- **The scoping answer itself is still vague** ("whatever you think is
  useful"). Proceed on Minty's own best-reasoned interpretation, and state
  plainly what interpretation was used, rather than looping the question.

## 11. Open product questions — not yet decided

- **How much fan-out is reasonable per pass before it needs to check back
  in?** A handful of angles is fine; ten is probably not, and there's no
  rule yet for where that line sits.
- **Does this need a distinct name/trigger phrase of its own**, or does it
  live as an extension of an existing skill's entry point? Not decided —
  naming it prematurely risks baking in a scope decision that hasn't
  actually been made.
- **Quick take vs. deep dive** — should the user be able to signal "just a
  fast gut-check" vs. "go deep" up front, or is that exactly what the
  scoping question in §4 already covers implicitly?
- **Multi-bucket filing** (§8) — when a pass genuinely spans a sector file
  and a theme file, is that two writes, one cross-referenced pair, or does
  it need a different structure entirely? Flagged, not resolved.
