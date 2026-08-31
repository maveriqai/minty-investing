# Research Discovery — Solutioning / Architecture (built 2026-08-31)

Companion to `research-discovery-experience.md` (product/UX view, read that
first — this doc doesn't repeat the user-facing walkthrough). Captures how
the idea there could actually be built against this engine, informed by
external precedent researched 2026-08-30 (sources at the bottom).

**Status note (2026-08-31):** the split argued for below — a step inside
one skill for scoping, handing off to a separate staged skill for
gather/synthesize — shipped as `research-discovery` +
`research-discovery-gather` (`b6ddc90`, fixed same day in `2ae8273`). See
`research-discovery-plan.md` for the as-built engineering detail; this doc
stays as the record of why that shape was chosen over the alternatives in
§1.

## 1. Correcting the naive decomposition

The instinct to split "clarify," "identify angles," and
"orchestrate/synthesize" into three separate mechanisms doesn't map
cleanly onto what this engine actually has. Worked through against the
real primitives:

- **Not a system prompt.** `_SYSTEM_PROMPT`
  (`engine/harnesses/claude_agent_sdk.py`) is reserved for behavior that
  must fire on every turn regardless of which skill (if any) matched —
  currently four things, all justified by needing to work even on a
  skill-less ad hoc message. A scoping question only makes sense once
  skill-matching has already decided "this is an open-ended research
  request" — putting it in the system prompt would fire it on every
  message in the product, including ones that were never ambiguous.
- **Not a separate "clarify" skill.** Splitting clarify from the rest
  into two independently-triggered skills means the model has to
  re-decide, after the user answers, whether the second skill's
  description still applies — reintroducing the soft-routing uncertainty
  every skill's disambiguation clause exists to avoid.
- **Is a step inside one skill**, same shape as `screen-indian-stocks`
  step 2 confirming a sector mapping, or `thesis-tracker` step 2 asking
  for pillars. Confirmed as the right shape by external precedent too —
  see §2.

"Orchestrate and synthesize... like staged skills but more generic" is
the one piece that's a real, confirmed gap, not a naming problem — see
§3.

## 2. External precedent

Four references, each mapping onto a specific piece of this design.
(Full context on the research pass itself, and citations, in the
conversation this doc came out of — summarized here for what's directly
actionable.)

- **Anthropic's own multi-agent research system**
  (orchestrator-worker: a lead agent plans and delegates to subagents,
  each with "an objective, an output format, tool/source guidance, and
  clear task boundaries," running with separate context windows, then
  synthesized). Three takeaways:
  - **"Scale effort to query complexity" as an explicit prompted rule** —
    their own early failure mode was "agents spawning 50 subagents for
    simple queries" without it. Confirms the plan below's angle cap isn't
    excess caution; it's a documented real failure class from the team
    that built the reference pattern.
  - **A dedicated, separate pass for citation attribution**, not trusting
    inline model citation — validates what Minty already does (the
    engine builds the Sources footer mechanically from actual captures,
    per `engine/sources_footer.py`); nothing to change here.
  - **An explicit caution against multi-agent for domains with heavy
    cross-agent dependency.** Investment research angles are often
    *not* independent — portfolio-relevance depends on which candidates
    the company-level angle found; policy context can reframe how to
    read a company-level finding. This argues for **sequential,
    context-passing stages** over fully-parallel isolated-context
    subagents — see §4.
- **`langchain-ai/open_deep_research`** — an actively maintained
  implementation of almost exactly this shape:
  `clarify_with_user` → `write_research_brief` → supervisor-dispatched
  researcher subagents → `final_report_generation`.
  - `clarify_with_user` is its own graph node, skippable — confirms
    clarification belongs as a step, and that "skip when unneeded" is
    load-bearing, not an afterthought.
  - `write_research_brief` uses a **structured output schema**
    (`ResearchQuestion`), not free prose. Directly adoptable: the
    "identify angles" stage should write a small structured plan file,
    same convention as every other Minty script's JSON output
    (`list_candidates.py`, `screen_rank.py`), not prose a later stage has
    to parse loosely.
  - **The dynamic fan-out is explicitly capped**:
    `allowed_conduct_research_calls =
    conduct_research_calls[:configurable.max_concurrent_research_units]`
    — overflow calls get error messages, not silent drops or unbounded
    execution. The real answer to "more generic than staged skills":
    dynamic count, but always through a hard ceiling.
  - **Final synthesis concatenates all findings with token-limit retry/
    truncation logic** — a documented version of the exact failure class
    `morning-digest` already hit (dropped output under a large single
    turn, the bug `staged_skills` itself exists to fix). Whatever
    synthesis stage gets built here needs the same defensiveness.
- **`gpt-researcher`** — planner → concurrent executors → publisher. Same
  shape, simpler, useful as a "minimal version" comparison point, not a
  design source in its own right.
- **LangGraph's `Send()` API** — the actual mechanism under dynamic
  fan-out elsewhere: `Send` objects are built inside a routing function
  *while the graph runs*, not fixed at compile time. This is the named
  version of the exact gap in `run_staged_skill`'s fixed
  `for stage in stages:` loop (§3) — a known pattern (map-reduce over
  dynamically-sized work), not something to invent from scratch.

## 3. The confirmed engine gap

Read `engine/staged_skills.py` directly. `run_staged_skill` iterates
`for stage in stages:` — a list loaded once from `SKILL.md` frontmatter
at skill-load time (`engine/skills.py`'s `load_stages`), before any
session runs. Each stage's `instructions` are hand-authored text baked
into the file. **No mechanism today lets one stage's own output decide
how many further stages run, or what they say.** `morning-digest` always
runs the same 4 named stages, every time.

That's the real, confirmed version of "more generic than staged skills":
not a vague desire for flexibility, but a specific, missing capability —
runtime-determined stage count and content.

## 4. Proposed architecture

### v1 — buildable now, zero engine changes

One skill (name/trigger not decided — see `research-discovery-
experience.md` §11), unstaged, steps:

1. **Clarify** — ask one scoping question only if two reasonable
   interpretations of the request would lead to genuinely different
   work (see experience doc §4's test). Otherwise skip straight to 2.
2. **Check the workspace** — `Glob`/read across `research/**/*.md`,
   `theses/*.md`, and `notes.md` for anything already relevant, before
   spending a single fresh tool call. Missing from the first draft of
   this section — flagging that it's its own step, not folded silently
   into step 4, since what's already known should shape which angles are
   even worth fresh work (an angle fully answered by an existing note
   gets cited, not re-gathered).
3. **Identify angles** — write a small structured plan (which angles,
   what to look up for each, and which ones step 2 already answered),
   **capped at 3 fresh angles**. Same convention as `list_candidates.py`'s
   JSON output, not prose. The cap is the "scale effort to complexity"
   guardrail from §2, made concrete as an actual number rather than a
   vibe. If more than 3 genuinely relevant angles surface, the plan says
   so explicitly and states which got deprioritized and why — never a
   silent truncation, same "overflow gets an explicit message, not a
   silent drop" discipline as `open_deep_research`'s concurrency cap.
4. **Gather** — for each planned fresh angle, make the tool calls it
   calls for, within this same turn/session.
5. **Synthesize** — compose one coherent brief organized by angle,
   blending fresh findings with what step 2 already had on file, explicit
   about what wasn't found (experience doc §6-7).

No new engine primitive — this is ordinary `SKILL.md` prose, same
mechanism every existing skill already uses. A 3-angle cap keeps total
tool-call volume nowhere near `morning-digest`'s ~70-call scale that
actually caused a real failure.

### v2 — dynamic staged execution, deferred deliberately

Not built until v1 demonstrates the same failure class `staged_skills`
itself was built to fix (measured, real output dropped under load) — same
discipline this codebase has followed every time (`staged_skills` itself
only came after a live-reproduced 98-holding/70-call bug, never
proactively; RAG deferred until notes actually stop fitting; #29's
staleness tracking deferred until a real observed failure). If/when that
trigger fires, the shape informed by §2-3:

- A fixed, hand-authored **planning stage** (structurally like today's
  first stage in any `stages:` list) whose `produces` is a structured
  plan file — the JSON artifact from v1's steps 2-3, generalized.
- The orchestrator (`run_staged_skill` or a new sibling function) reads
  that file back and constructs **N gather-stages at runtime**, each
  built the same way `_build_stage_prompt` builds one today, just with
  per-run instructions instead of frontmatter ones.
- **A hard count cap**, mirroring `open_deep_research`'s
  `max_concurrent_research_units` slicing — but as a *count* cap, not a
  *concurrency* cap: per §2's Anthropic caution, Minty's stages should
  stay **sequential** (one fresh session at a time, like every staged
  skill today, via `needs`/`produces` file-passing between them), not
  `asyncio.gather`-parallel like Anthropic's/LangGraph's isolated-context
  subagents. Minty's research passes are small-count and often
  interdependent — sequential stages that can read a prior stage's output
  file fit that better than parallel subagents that can't see each
  other's work until a synthesis step reconciles them.
- A fixed final **synthesize stage**, closing the same way `compose`
  does today — with the same token-limit defensiveness
  `open_deep_research`'s `final_report_generation` needed, since
  concatenating N stages' findings into one synthesis prompt is exactly
  the shape that caused `morning-digest`'s original citation-dropping bug.

## 5. How close is this to Anthropic's own multi-agent system

Worth being precise about, since "more generic than staged skills"
invites the assumption this is a scaled-down clone of §2's reference
architecture. It borrows explicit principles — cited there — but diverges
structurally in three deliberate ways, not accidental simplifications:

| | Anthropic's system | V1/V2 here |
|---|---|---|
| **Execution model** | Lead agent + subagents, genuinely **parallel**, each with an **isolated context window** | V1: **one session**, sequential steps — not multi-agent at all, closer to a structured single skill turn. V2: dynamically-sized but **sequential** fresh sessions, one at a time |
| **Iteration** | Lead agent can decide "more research needed" and **re-delegate** — a feedback loop between synthesis and further research | **Single fixed pass** — plan once, gather once per angle, synthesize once. No loop-back designed |
| **Scale/cost** | Hosted product feature, 10+ concurrent subagents for complex queries, explicitly token-hungry ("token usage explains 80% of variance"), sized for serving many users at real compute budget | Local, single-user tool — capped at 3 angles (v1) or a still-small explicit ceiling (v2), no concurrency, sized to Minty's own economics |

The parallel-vs-sequential divergence is the largest one, and it's
deliberate, straight from Anthropic's own stated caution in the same
source: "domains that require all agents to share context or involve many
dependencies between agents are not a good fit for multi-agent systems."
Investment research angles here are often interdependent (portfolio
relevance depends on what the company-level angle actually found) — the
actual argument for staying sequential, not a resource shortcut.

Net: directionally inspired by it (the planning discipline, the explicit
cap, structured-artifact-over-prose), architecturally much smaller, and
diverging from it in exactly the place their own writeup says to. V1 in
particular isn't a lightweight multi-agent system at all — it's a single
structured skill turn that borrows multi-agent *planning discipline*
without being multi-agent.

## 6. How V1/V2 handle the research scenarios already discussed

A design that only works for the motivating example (PLI-semiconductors)
isn't actually validated. Traced through every scenario named across this
conversation and #40/#56/#57.

**The routing boundary comes first**, since it decides whether V1/V2 even
engages: the same skill-matching mechanism every existing skill already
uses (§1's disambiguation-clause convention) — this new skill's own
description should trigger only on asks no narrower skill already answers
cleanly. So the real dividing line isn't "sector vs. symbol vs. theme,"
it's **whether one existing skill already covers the ask**.

| Scenario | Routed to | How it's handled |
|---|---|---|
| "Screen the auto sector" | `screen-indian-stocks` directly | V1/V2 never engages — one angle, one existing skill, today's behavior unchanged |
| "Check XYZ for red flags" / "update my thesis on X" | `red-flag-scan` / `thesis-tracker` directly | Same — crisp, single-tool ask |
| "What do you think of TATAMOTORS" (broader than a governance check — fundamentals + news + fit) | V1 | A case for V1 even though the key is one symbol — the boundary is breadth of the ask, not whether it's sector/symbol/theme-shaped. Corrects the experience doc §4 framing, which read as "already a symbol → always skip V1"; it should route away only when the ask is *also* narrow |
| "PLI-scheme beneficiaries" (#57) | V1 | The motivating case: clarify (pure-play vs. broader supply chain) → workspace check → identify angles (policy context, candidate companies, portfolio relevance) → gather → synthesize. **Real limitation, not fixed by V1/V2 at all**: if no data source exists for "which companies are PLI beneficiaries," synthesis reports that gap honestly — V1/V2 solves the *orchestration* half of #57, not the *missing data source* half, which stays a separate, unsolved problem (evaluated, not resolved, in §7) |
| "What's driving FII outflows this month" (macro, unfiled gap) | V1 | Actually the cleanest fit — its angles (FII/DII flow data, recent news, historical pattern) each map to an existing MCP tool with no missing-data-source gap the way #57 has, so V1 likely produces its most complete answer here |
| Already-researched subject asked again | V1/V2 step 2 (workspace check) | Leads with what's already known, only gathers what's genuinely new — the step just added back into §4 after noticing it was missing |
| No data source for part of the ask ("options trader positioning") | V1 step 3 (plan) / step 5 (synthesize) | That angle gets dropped or flagged unanswerable in the plan; synthesis states the gap plainly and still delivers whatever else it could source |
| Vague scoping answer ("whatever's useful") | V1 step 1 | Proceeds on best-reasoned interpretation, states which one was used, doesn't loop the question |
| More than 3 genuinely relevant angles | V1 step 3 | Picks the most decision-relevant 3, states explicitly which got deprioritized and why. **If this turns out to be common in practice, that's the concrete signal it's time to build V2** — not a reason to raise V1's cap arbitrarily |
| User wants to commit to a thesis on a name surfaced this way | The existing #40 §2.5 bridge | Unaffected — the bridge checks `research/*.md` regardless of which skill wrote the file, so V1/V2's output composes with it for free as long as it files into the same bucket conventions |
| A pass genuinely spans two buckets (a theme file and a portfolio-relevance note) | Unresolved | Same open question as experience doc §8/§11 — V1's architecture doesn't block a multi-bucket write, but the mechanics aren't decided |

Two honest gaps this trace surfaces, not solved by anything in this doc:
**#57's missing candidate-data-source problem** (a data problem, not an
orchestration one) and **multi-bucket filing** (still open). Everything
else in the list is either already handled by existing skill-routing, at
zero added cost, or falls cleanly inside V1's five steps.

## 7. Web search for #57's missing-data-source gap — evaluated, not decided

Explored directly, since §6 named "no source exists for which companies
are PLI beneficiaries" as a real gap V1/V2's orchestration doesn't touch
on its own.

### Why this isn't a simple engine-config toggle

Tension with two decisions already made in this codebase, not just
abstract caution:

- **Issue #25** already removed Bash for exactly this shape of problem —
  its one real exercised use (fetching a filing PDF directly) "bypassed
  `mcp/common/nse_fetch.py`'s cache/throttle/circuit-breaker and Minty's
  auto-capture/Sources-footer grounding entirely, with no scoping ever
  actually enforced." A bare web search tool has the same risk profile:
  no caching, no rate-limiting, no domain curation, no
  `{"source","as_of","data"}` envelope any other tool in this product
  returns.
- **Issue #54** (filed earlier this session) argues Minty's minimal tool
  surface — no Bash, no WebFetch/WebSearch — is what makes "Minty
  structurally can't act outside investing" a real property, not an
  aspiration. Adding web search directly widens that exact boundary.
- **Mechanically**: `builtin_tools` is set once, globally, per session
  (`engine/config.py`) — there's no way today to scope a tool to one
  skill's one step. Enabling it for #57's candidate-sourcing gap means
  every skill and every ad hoc conversation gains it, not just this one
  narrow case.

### Three refinements considered, each building on the last

**1. Citations (Anthropic's Citations API).** Real, documented
infrastructure, not something to build: source content is chunked
(sentence-level), and any claim Claude generates from it carries a
citation back to the exact passage — explicitly built to compose with
Claude's own web search tool ("when the web search tool is enabled in
the same request, citations must be enabled on all `search_result`
blocks"). Closes fabrication/traceability. Leaves open: source quality
itself (a citation makes a bad source *visible*, not filtered out —
visibility isn't curation), caching/politeness, and per-skill scoping.

**2. Last-resort ordering.** "Try existing tools first, web search only
when nothing else can satisfy the need" — directly distinguishes this
from what got rejected in #25 (Bash had no ordering discipline at all).
As a prompt instruction alone it's a judgment call about semantic
sufficiency, not mechanically checkable — same soft trust tier as
skill-routing. A `PreToolUse` hook (same mechanism as the existing
order-tool deny hook) can enforce a cheaper, real version: deny the call
unless another MCP tool has already been called this turn. Can't verify
the existing tools were *actually enough*, but guarantees they were at
least tried — a genuine code-enforced floor, not just a hope. Because
this rule needs to hold everywhere the tool exists, not just inside one
skill, it belongs in `_SYSTEM_PROMPT`, not skill-local prose — same shape
as the existing Kite-login disclosure rule.

**3. Gate it behind a Minty-owned tool — the strongest option, converts
most of the rest into code-level guarantees instead of prompt-level
hopes.** Wrap it as a new Layer 2 MCP server (`mcp/research_web_search/`
or similar), same pattern as `india_price`/`india_screener`: single-file
`server.py`, shared fetch/cache/rate-limit code from `mcp/common/`, a
`{"source", "as_of", "data"}` envelope. Concretely:

- **Caching/politeness** — solved outright by reusing `mcp/common`'s
  existing shared fetch/cache/rate-limit code, the same discipline
  CLAUDE.md already requires. No new pattern.
- **Source quality** — the real upgrade over citations alone: a
  Minty-owned tool can filter or curate results *before the model ever
  sees them* (a domain allowlist, a basic quality check), enforced
  deterministically in the tool's own code — not a hope the model judges
  correctly at read-time.
- **Grounding at the tool-call level, effectively for free** — a
  standard envelope means the existing `engine/tool_capture.py`
  auto-capture and Sources footer cover it automatically, same as every
  other tool. But this only proves *a call happened and returned real
  content* — it doesn't prove a specific sentence in the model's
  synthesized answer actually maps to a specific passage within that
  content. That gap matters more here than for any other Minty tool:
  `india_price`/`india_filings`/etc. return single structured facts (a
  P/E ratio, a filing date) with no synthesis step between "what the tool
  returned" and "what gets narrated." Web search results are unstructured
  prose across possibly several pages that the model has to read and
  rephrase — exactly the shape of task where a model can blend or subtly
  misattribute content while summarizing, and a tool-call-level citation
  can't catch that; only a sentence-level one can. Citations aren't a
  redundant nice-to-have on top of the envelope — they're answering a
  different question than the envelope does. See below.
- **Containment (#54)** — meaningfully narrower than a generic grant: the
  model gets a Minty-defined tool with a Minty-defined shape ("find
  companies matching a theme," not "search the web"), even though the
  implementation reaches the open web underneath. The tool surface stays
  domain-shaped.
- **Precedent (#25)** — this *is* the governed-replacement pattern #25
  already established (Bash → `india_filings.get_filing_document`,
  explicitly named "the governed replacement" in `engine/config.py`'s own
  comment), applied to a new case — not a new risk, the same fix again.
- **Per-skill scoping — a real, precedented path, not just a wish.**
  `_build_options` (`engine/harnesses/claude_agent_sdk.py`) already
  conditionally registers `staged_workflows_server` only when the
  invoked skill list actually needs it
  (`if tools.include_staged_tools and staged_skill_names:`). A dedicated
  `research_web_search` server could follow the exact same pattern —
  registered only when the research-discovery skill is in play, not
  engine-wide by default.
- **What it still doesn't solve alone**: a tool handler has no visibility
  into what else was called earlier this turn — that context lives at
  the engine/session layer. Refinement 2's `PreToolUse` tripwire still
  earns its place *alongside* this, not instead of it.

### Where this leaves it

Updated lead position: gate behind a new, Minty-owned Layer 2 MCP server
— not Anthropic's raw web-search built-in — combining all three
refinements, with citations required rather than optional (corrected
from an earlier pass through this doc, which called them a nice-to-have
once the tool wrapper's envelope existed — wrong: the envelope and
citations answer different questions, and dropping either leaves a real
gap):

1. **Citations required, not optional** (refinement 1) — the envelope
   grounds that a call happened; citations ground that a specific
   narrated sentence traces to a specific passage within an unstructured,
   multi-page result. Web search is the one Minty tool shape where the
   model does real synthesis across prose rather than relaying a single
   structured fact, which is exactly where that gap is most exploitable
   and least caught by anything else in this design. The underlying
   implementation should call Claude's own web search tool specifically
   so Anthropic's Citations API is available at all (`search_result`
   blocks with citations enabled), and the tool's own envelope should
   carry that citation data through rather than discarding it.
2. A `PreToolUse` tripwire enforcing "tried another MCP tool first this
   turn" (refinement 2).
3. Server-side domain curation/filtering, not just citation-based
   visibility (refinement 3).
4. The standard `{"source", "as_of", "data"}` envelope, extended to
   preserve per-result citation data rather than collapsing it to
   tool-call granularity (refinement 3, corrected).
5. Registered only for the skill(s) that need it, via the same
   conditional-registration pattern `staged_workflows_server` already
   uses (refinement 3).

Still not decided: the exact domain-curation policy, and whether this
ships as part of #57's eventual fix or stays a named, deferred option.
Search provider is no longer fully open, given (1) above — it needs to be
Claude's own web search tool specifically, not an arbitrary third-party
search API, for the Citations API to apply at all.

## 8. What v2 would actually require, mechanically (sketch, not a spec)

Flagged for whoever picks this up — not resolved here:

- A new stage "kind" distinguishing a fixed planning/synthesis stage from
  a dynamically-generated gather stage, since `_validate_stage_order`
  (`engine/skills.py`) currently assumes every stage is declared, fixed,
  and known at load time.
- `_build_stage_prompt` needs to accept per-run generated `instructions`
  text, not only the frontmatter-authored kind it takes today.
- Fail-open/`critical` semantics (§9 of `staged-skill-execution-design.md`)
  need a story for a dynamically-generated stage — does one failed
  gather-stage abort the rest, or does the synthesis stage just note the
  gap the way v1's step 4 already would?
- Audit logging and Sources-footer aggregation (`all_captures`) already
  just extend across however many stages ran (`run_staged_skill`'s own
  loop) — this part likely needs no change, since it was never written
  assuming a fixed stage count in the first place.
- Real testing implications: today's staged-skill tests exercise a fixed,
  known stage list; this needs cases for a plan file producing 1 angle,
  the cap, and a plan file that fails to parse.

## 9. Explicitly not decided here

- Which existing skill(s) this feeds output into (`research/sectors/`,
  `research/stocks/`, `research/themes/` from #40/#56/#57) — see
  experience doc §8.
- Whether v1 ships as a wholly new skill or an extension of an existing
  one, and what its trigger phrase is — experience doc §11.
- The exact plan-file schema for v1's step 2 — sketched in spirit above
  (angle id + what to look up), not specified.

## Sources

- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research)
- [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher)
- [LangGraph Send() API — dynamic parallelism](https://medium.com/@vishy2k5/langgraph-send-api-7aaab56bc6b8)
