# Research Discovery — Implementation Plan (full sequential-staged + web-search system, initial target)

Companion to `research-discovery-experience.md` (product/UX rationale) and
`research-discovery-architecture.md` (why this shape, the Anthropic
comparison, the web-search evaluation). **Supersedes this doc's earlier
"V1 now, defer V2" version.** Deliberate decision, made explicitly: build
the full sequential-staged + web-search system as the initial target,
accepting the tradeoff this was weighed against — every other generic
mechanism in this codebase (`staged_skills` itself included) was built
only after an observed real failure, never proactively; this one is
designed ahead of that evidence. What doesn't change regardless of that
decision: sequential, not parallel (architecture doc §5); single-pass,
not iterative; scoped to research-discovery's own concerns, not #40/#56/
the-thesis-bridge's separate, still-open piping work (previous turn's
audit).

## 0. What "the initial target" actually consists of

Three pieces landing together, not sequentially:

- **A.** Two skill directories, not one — `research-discovery` (plain,
  natively invoked) and `research-discovery-gather` (staged-only). Split
  forced by a real mechanical finding, not a stylistic choice — see §1.
- **B.** A new Layer 2 MCP server, `mcp/research_web_search/`, gated and
  citation-required (architecture doc §7).
- **C.** New engine code: dynamic stage generation in `staged_skills.py`
  — the single biggest genuinely new primitive this plan requires, and
  the part with the most real engineering risk.

## 1. Why two skills, not one — the mechanical finding this is built on

Confirmed directly from `engine/staged_skill_tools.py`, not assumed:

- A staged run **cannot pause mid-way for the user.** Its own tool
  description: *"Call this once for the whole run — don't call it
  repeatedly, and don't expect intermediate output back before it
  returns."* A code comment states it even more plainly: *"this handler
  is one atomic call with no way to pause for user input."*
- The staged tool's **input schema takes exactly one parameter**,
  `workspace_root` — no mechanism exists today for the user's actual
  request to reach a staged run at all. Every existing staged skill
  (`morning-digest`) never needed this, since its stages are identical
  every run.
- A skill declared with `stages:` is **excluded from native
  skill-loading** — *"never also left in `tools.skills` for native
  Skill-invocation... one entry point, no competing path"* — so there's
  no way to bolt a pre-staging clarify step onto a staged skill's own
  definition either.

LangGraph (underneath `open_deep_research`, discussed and rejected as
infrastructure to adopt) has a real, structural answer to this — a graph
node can interrupt, return control, and resume later. Minty doesn't have
that primitive, and building a general version of it is a bigger, less
justified engine feature than this one skill's need warrants. The
pragmatic native equivalent: split clarify out into its own plain skill
turn (which already has real multi-turn pause-and-resume — `thesis-
tracker` proves this works today), and hand off to a staged back half via
a file on disk, using the `needs`/`produces` mechanism that already
exists and needs no schema change.

## 2. Part A1 — `research-discovery` (plain, native front door)

### Skill identity

- **Name**: `research-discovery`
- **Directory**: `.claude/skills/research-discovery/`
- **Trigger description** (unchanged from the earlier plan — the routing
  boundary doesn't depend on execution shape):

  > Use when the user has an open-ended research question that doesn't
  > map cleanly to one existing skill — a headline, a tip, a vague hunch,
  > or a cross-cutting question with no single sector/symbol ("what's
  > driving FII outflows", "PLI scheme beneficiaries", "should I be
  > worried about X given the rupee"). Not for a request that already
  > names a clean sector (use screen-indian-stocks), a specific stock
  > needing a governance check or thesis update (use
  > red-flag-scan/thesis-tracker), or a portfolio-wide review (use
  > portfolio-health-check).

### Frontmatter

```yaml
---
name: research-discovery
description: >
  [trigger description above]
expected_outputs: []  # this skill produces no final output of its own —
                       # research-discovery-gather's synthesize stage does
---
```

No `deterministic_scripts`, no `tool_call_budgets` — this skill makes at
most a handful of `Glob`/`Read` calls (workspace check) and one tool call
(the handoff); nothing here fetches external data.

### Body — four steps

1. **Clarify — only if genuinely ambiguous.** Unchanged from the earlier
   plan: exactly one scoping question, only when two reasonable
   interpretations would lead to meaningfully different work. Real
   multi-turn pause here — same proven mechanism `thesis-tracker` already
   uses, not staged, so no mechanical risk.
2. **Check the workspace.** `Glob`/read across `research/sectors/*.md`,
   `research/stocks/*.md`, `research/themes/*.md`, `theses/*.md`,
   `notes.md`. Unchanged from the earlier plan.
3. **Identify up to 6 fresh angles** (raised from V1's flat 3 — the whole
   point of building the staged back half is headroom for larger passes
   without the dropped-output risk a single turn has). For each: what
   it's trying to answer, which tool(s) it needs, and — carried forward
   from step 2 — which angles are already answered and don't need fresh
   work. If more than 6 genuinely relevant angles surface, state which
   got deprioritized and why, same "never silent" rule as before.
4. **Write the plan and hand off.** Call `update_workspace_notes` with
   `target` = `data/research_plan_<slug>_<date>.json` (a fourth
   allow-listed pattern, §5 below) — `<slug>` a short identifier for this
   run, doesn't need to match whatever bucket the result eventually files
   into. Content: a JSON object — `{"request": "<clarified request
   text>", "already_known": [...from step 2...], "angles": [{"id",
   "question", "tool_hint"}, ...]}`. Then call
   `run_staged_research-discovery-gather` with `workspace_root`. Relay
   that tool's own returned text as this skill's reply — don't
   re-narrate or summarize it.

### Guardrails

Same as the earlier plan's — no order tools, no direct
`kite_gateway.get_holdings`, one clarifying question maximum, India-market
conventions.

## 3. Part A2 — `research-discovery-gather` (staged-only back half)

Never natively invoked — exposed only via `run_staged_research-discovery-gather`.

### Frontmatter

```yaml
---
name: research-discovery-gather
expected_outputs:
  - "{workspace}/results/research_*_{date}.md"
stages:
  - id: gather
    dynamic: true          # NEW frontmatter concept — see §4
    needs:
      - "{workspace}/data/research_plan_*_{date}.json"
    produces:
      - "{workspace}/data/research_finding_*_{date}.json"
    max_instances: 6       # hard orchestrator-level cap, independent of
                            # whatever the plan file itself claims
  - id: synthesize
    critical: true
    instructions: |
      Glob for {workspace}/data/research_finding_*_{date}.json yourself
      (the exact count varies — don't rely on a needs/produces listing
      built for a fixed count) and read each one. Also read the plan
      file's own "already_known" section. Compose one brief organized by
      angle, blending fresh findings with what was already known,
      explicit about any angle whose finding file is missing (report as
      a gap, never filled from memory). Decide which research/ bucket(s)
      this belongs in (sectors/stocks/themes, based on what the research
      turned out to be about) and call update_workspace_notes for each.
      Don't write a Sources footer or SEBI disclaimer — the engine
      appends both automatically.
    produces:
      - "{workspace}/results/research_*_{date}.md"
---
```

### The `dynamic: true` gather stage — how it actually runs

Not a per-angle skill file — one stage *template*, expanded by the
orchestrator at runtime into N concrete stage instances, each run exactly
like an ordinary stage (fresh session, `_build_stage_prompt`, its own
audit log, fail-open by default — one angle's finding going missing
doesn't abort the run, `synthesize` just reports that gap). Each
instance's own `instructions` text is built from the corresponding
angle's `question`/`tool_hint` in the plan file, not hand-authored in
frontmatter — the one genuinely new kind of per-stage prompt content this
engine will have.

Fail-open applies per-instance, not to the whole dynamic block — a single
angle's gather-stage failing doesn't cancel the other angles' stages, it
just means one missing `research_finding_*.json` for `synthesize` to
report honestly. `synthesize` itself stays `critical: true`, matching
issue #52's precedent — if it fails to produce a real result, the run
should surface that plainly rather than silently returning stale or
partial output.

## 4. Part C — the new engine primitive (the biggest real risk in this plan)

`run_staged_skill`'s current loop (`engine/staged_skills.py`) iterates a
fixed `stages` list, computed once at skill-load time. This needs new
logic, roughly:

1. **`engine/skills.py`'s `load_stages`/`_validate_stage_order`** needs
   to accept `dynamic: true` + `max_instances` on a stage entry, and
   validate it the way `critical` is validated today (a `dynamic` stage
   with no `needs` pointing at a JSON plan file is rejected at load time,
   same bar as a `critical` stage with no `produces` being rejected now).
2. **`run_staged_skill`'s loop**, on reaching a stage marked `dynamic`:
   - Confirms the plan file (`needs`) is actually present — if missing,
     this behaves like any other stage with an unmet `needs`: proceeds,
     but the expansion step below has nothing to expand, so zero
     instances run and `synthesize` reports the whole pass as empty.
   - **Reads and JSON-parses the plan file itself** (new — every other
     `needs` check today only tests existence via `_exists()`, never
     reads content). Extracts `angles`, caps at `max_instances`
     (`open_deep_research`'s own `max_concurrent_research_units` slicing
     is the direct precedent for this exact shape of cap — enforced by
     the orchestrator, not left to the model's own prose discipline,
     since a raw call-count ceiling is mechanically checkable even though
     "was this angle actually worth pursuing" isn't, per the same
     asymmetry already established for the web-search tripwire in
     architecture doc §7).
   - For each surviving angle, builds a concrete stage dict (`id`,
     `instructions` from the angle's own `question`/`tool_hint`, `needs`
     = the plan file, `produces` = that angle's own finding-file
     pattern) and runs it through the **existing** per-stage execution
     path unchanged — fresh session, prompt-building, audit logging,
     fail-open capture — no new code needed for the actual running of
     each expanded instance, only for generating them.
   - Continues to the next declared stage (`synthesize`) once every
     expanded instance has run, same as today's loop moving to the next
     list entry.
3. **Testing implications**: today's staged-skill tests exercise a fixed,
   known stage list. New cases needed: a plan file with 1 angle, a plan
   file at the cap, a plan file over the cap (confirms the extra angles
   get dropped, not silently run anyway), a missing/malformed plan file
   (confirms `synthesize` still runs and reports the gap rather than the
   whole pipeline crashing).

## 5. Part B — the web-search MCP server

Per architecture doc §7's already-settled position: `mcp/research_web_search/`,
same pattern as `india_price`/`india_screener` — single-file `server.py`,
shared fetch/cache/rate-limit code from `mcp/common/`, a `{"source",
"as_of", "data"}` envelope that preserves per-result citation data rather
than collapsing it to tool-call granularity.

**One dependency this plan surfaces for the first time, not previously
named anywhere in this design**: for citations to exist at all, the
server's own handler needs to make a real call to Claude's web search
tool *with citations enabled* — which means the MCP server process itself
needs its own path to the Anthropic API, separate from however the main
engine's `ClaudeAgentSDKHarness` session authenticates (`docs/vision.md`
§8 notes that path reuses an existing Claude Code/subscription login, not
a raw API key). Whether a Minty-owned tool server can piggyback on that
same auth, or needs its own `ANTHROPIC_API_KEY` and a real billing
consideration, isn't resolved by anything designed so far — flagged here
as a genuine open dependency, not assumed away.

Registration: conditional, following the exact pattern
`staged_workflows_server` already uses in `_build_options` — only
registered when `research-discovery`/`research-discovery-gather` are
actually in the invoked skill set, not engine-wide by default.

Domain-curation policy, the `PreToolUse` "tried another MCP tool first"
tripwire, and the exact citation-in-envelope shape all still need their
own design pass before this is buildable — architecture doc §7 evaluated
the *shape* of the fix, not the concrete server code.

## 6. Prerequisite/shared engine change

Extend `engine/workspace_notes.py`'s `_resolve_target` allow-list to four
patterns, not three — the earlier plan's `research/sectors/`,
`research/stocks/`, `research/themes/` regexes, plus:

```python
_RESEARCH_PLAN_RE = re.compile(r"^data/research_plan_[a-z0-9]+(-[a-z0-9]+)*_\d{4}-\d{2}-\d{2}\.json$")
```

Same tool, same "engine decides where, model decides what" convention —
no new tool needed just for the plan-file handoff.

## 7. Testing plan

- `tests/test_engine_workspace_notes.py` — all four target patterns, same
  shape as existing `theses/` coverage.
- New tests for `dynamic: true` stage expansion (§4.3 above).
- Live-verification checklist, carried forward from the earlier plan
  unchanged: crisp asks never reach `research-discovery`, exactly one
  clarifying question when genuinely ambiguous (same #31-precedent
  reliability risk, same escalation trigger — a bigger execution shape
  doesn't make this judgment call more reliable, per last turn's finding
  that "more architecture" doesn't fix it), already-researched subjects
  lead with what's known, angle-overflow states what got deprioritized,
  an unanswerable angle is reported honestly.
- New: a run where one dynamically-generated gather stage genuinely fails
  (bad tool call, no data) — confirms `synthesize` still completes and
  names the gap, rather than the whole run aborting.

## 8. Explicitly not decided / next design passes needed before build

- The web-search server's own auth path (§5) — needs resolving before
  that piece is buildable at all, not just before it's polished.
- Domain-curation policy for web search — still just "should exist," not
  specified.
- Multi-bucket filing mechanics (`synthesize` deciding to write more than
  one `research/` bucket) — same open item as every prior doc, not
  resolved by this plan either.
- Exact plan-file JSON schema above is a sketch, not a finalized contract
  — worth a short review before code gets written against it.
