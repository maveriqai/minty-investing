# Staged Skill Execution — Design Doc (built and live-verified, 2026-08-08)

## 1. Problem

`morning-digest` silently drops real, successfully-fetched data from its
own Sources footer on a large portfolio. Confirmed live 2026-08-05 against
a real 98-holding account:

- The digest ran as one continuous turn (`ClaudeSession.send()`, one
  `session.send()` call) spanning ~70 tool calls over ~31 real minutes:
  holdings → live quotes (batched) → `run_digest_math` →
  `run_surveillance_check` + ASM/GSM lists → 18×`get_announcements` +
  18×`get_news` (step 8's bounded set) → `run_materiality_check` → compose.
- 29 `india_news.get_news` calls actually happened (confirming the
  known duplicate-query issue — raw ticker + company name — is still
  live even after tightening the SKILL.md prose). Only 18 of those 29
  calls made it into the turn's `captures` list, and therefore into the
  Sources footer. The other 11 files exist on disk (auto-capture's
  `save_tool_result` really did write them) but the turn's own
  bookkeeping never saw them.
- Root-caused as far as practical without a much larger investigation:
  **not** a logic bug in the capture loop itself. A targeted repro —
  40 forced `india_news.get_news` calls, no other tool traffic, finished
  in a couple of minutes — captured all 40 with perfect 1:1
  `ToolUseBlock`↔`ToolResultBlock` pairing (verified with temporary debug
  instrumentation in `ClaudeSession.send()`, reverted after). The failure
  only shows up under the real digest's conditions: a very long, very
  large-context single turn. The timing evidence points the same way — an
  early, fast batch of calls (11 calls in under 2 minutes) captured
  cleanly; a later batch of calls, 60–90 seconds apart despite a 2-second
  throttle, is where captures start disappearing. That gap is far more
  consistent with the model's own per-call reasoning latency growing as
  context balloons than with network throttling.
- Best-supported (not confirmed) hypothesis: Claude Code's own context
  compaction, which triggers on accumulated context size rather than call
  count, is altering how some tool-call/tool-result pairs replay through
  `receive_response()` later in a very long turn — the write still
  happens, but the pairing this engine relies on to know it happened
  doesn't survive.

This matters beyond the news-duplication bug it was found investigating.
The Sources footer is a Non-Negotiable Product Rule
(`docs/vision.md` §5 — "every numeric claim traces to a tool result... a
Sources footer"). Right now that guarantee quietly degrades exactly when
a portfolio is large enough to need it most.

## 2. Why not fix the capture loop directly

Root-causing the actual compaction/pairing interaction would mean either
reproducing at real 98-holding scale repeatedly (~30 minutes per attempt)
or digging into Claude Agent SDK / Claude Code CLI internals neither of
which this project controls. Even if root-caused, the fix would still
leave one enormous turn as the unit of work — the same shape that made
the failure possible in the first place, and the same shape that makes
per-turn tool-call budgets, the Sources footer, and the `.md` snapshot all
inherently fragile for any future skill that scales with portfolio size.

The better fix is architectural: don't let one turn's context grow
unbounded in the first place.

## 3. Proposed direction: engine-orchestrated stages, not model-driven delegation

Two shapes were considered:

- **Model-driven subagents** — the SDK's own subagent/delegation
  primitive (comparable to Claude Code's Task tool). The model decides
  when to delegate to a fresh sub-context.
- **Engine-orchestrated staged pipeline** — the engine deterministically
  splits a skill's run into stages, each a fresh turn with a bounded
  prompt, driven by a declaration in the skill's own SKILL.md.

Rejecting the first: it hands the reliability-critical decision ("should
I delegate now, to keep context bounded") back to model judgment, which
is exactly the failure mode this whole project keeps finding and fixing
mechanically — the missing Sources footer, the missing `.md` save, and
the still-live news-duplication bug are all cases where a prose
instruction the model was supposed to follow reliably, didn't. Delegation
timing would be the same kind of instruction.

The second shape is a direct extension of the pattern already used
everywhere else in this engine: a skill declares structure in its own
SKILL.md frontmatter, and generic engine code (not per-skill Python) acts
on it. `engine/skills.py`'s own docstring already states this as the
deliberate alternative to the old repo's per-skill Python
stage-orchestration:

> "This is deliberately not `engine/digest.py`'s old per-skill Python
> stage-orchestration: that pattern was built for one skill run
> unattended, and doesn't scale to 'any contributor can add a skill via a
> SKILL.md, no engine code required'."

Staging is the same idea, applied to turn boundaries instead of output
files.

How a staged skill's run actually gets *triggered* — routed to from an
ordinary user prompt — turned out to need its own extended discussion;
see §8, which supersedes an earlier, since-abandoned idea (a `PreToolUse`
hook intercepting the model's native `Skill` tool call) in favor of
exposing staged skills as dedicated in-process tools instead.

## 4. The `stages` frontmatter field

New, optional, per-skill frontmatter — same file, same declarative
convention as `expected_outputs` / `deterministic_scripts` /
`tool_call_budgets`. A skill that doesn't declare `stages` keeps running
exactly as it does today, as one turn — this is opt-in, not a rewrite of
every skill.

Sketch:

```yaml
stages:
  - id: portfolio_and_market
    instructions: |
      Fetch current holdings and live quotes, then call run_digest_math.
      Save its output to results/digest_{date}.json.
    produces:
      - "workspaces/{workspace}/results/digest_{date}.json"
  - id: surveillance
    instructions: |
      Fetch the ASM/GSM surveillance lists and call run_surveillance_check
      against today's holdings. Save its output to
      results/surveillance_flags_{date}.json.
    needs:
      - "workspaces/{workspace}/results/digest_{date}.json"
    produces:
      - "workspaces/{workspace}/results/surveillance_flags_{date}.json"
  - id: news_and_materiality
    instructions: |
      Read results/digest_{date}.json for today's bounded symbol set. For
      each symbol, call get_announcements once and get_news once (symbol
      only, not company name). Call run_materiality_check. Save its output
      to results/materiality_flags_{date}.json.
    needs:
      - "workspaces/{workspace}/results/digest_{date}.json"
    produces:
      - "workspaces/{workspace}/results/materiality_flags_{date}.json"
  - id: compose
    instructions: |
      Read all three result files below and compose the morning digest
      brief. Any file missing from the list means that stage failed —
      say so explicitly in the relevant section instead of omitting it.
    needs:
      - "workspaces/{workspace}/results/digest_{date}.json"
      - "workspaces/{workspace}/results/surveillance_flags_{date}.json"
      - "workspaces/{workspace}/results/materiality_flags_{date}.json"
    produces:
      - "workspaces/{workspace}/results/digest_brief_{date}.md"
```

`produces` is optional per stage — a stage that declares nothing here is
simply never checked, same as a skill without `expected_outputs` today.
Where it is declared, it's checked mechanically (§5) right after that
stage's session closes, independent of whether the stage raised — the
same "don't trust the model's own account of what it did, check the
filesystem" pattern `expected_outputs`/`match_changed_files` already use
at the skill level.

`needs` reuses the exact glob-pattern-with-placeholders shape
`expected_outputs` already uses, resolved with the same
`resolve_pattern`/`REPO_ROOT.glob` machinery in `engine/skills.py` — no
new pattern language. This is the key mechanical property that makes
staging cheap to build: the hand-off contract between stages is *already
declared*, today, as each stage's own `expected_outputs` (or the
computed-file half of it) — `results/digest_<date>.json`,
`results/surveillance_flags_<date>.json`,
`results/materiality_flags_<date>.json` already are the small, computed,
stage-boundary artifacts. Staging doesn't invent a new hand-off format;
it just tells the engine which of those files a later stage should be
pointed at, instead of relying on that stage inheriting the full
conversation history that produced them.

**Decided (2026-08-05):** `instructions` is an authored block scalar
directly in the `stages:` frontmatter entry, not extracted from the
SKILL.md body. Rejected extraction because it conflates two different
audiences — SKILL.md prose is written for a human reading the skill,
with room for examples and rationale; a stage prompt is written to keep a
fresh session's starting context small and unambiguous — and because
string-matching a Markdown heading is a silent failure mode (rename or
reformat a heading, break a stage boundary with no error). This does mean
the `stages` entry is a second piece of text an author keeps loosely
aligned with the body prose, but it matches how `expected_outputs` and
`tool_call_budgets` already work: structured frontmatter values, not
values parsed out of body prose.

**The body is not replaced — it's shared context, sent to every stage.**
An earlier draft of this design left this unresolved, and a fair question
surfaced it: if the model-facing content per stage is just the authored
`instructions` string above, the SKILL.md **body** — the skill's own
description, its numbered steps, and critically its guardrails
(deterministic-calculation-only, the SEBI disclaimer framing, the
step-8b once-per-symbol fix) — is never actually read by the model in
staged mode. It would exist only as documentation for a human, while the
frontmatter YAML quietly became the real skill. That's a real regression,
not a cosmetic one: those guardrails not reaching the model is exactly
the class of failure (prose the model was supposed to follow, silently
didn't) this whole project keeps finding and fixing. And it would mean a
staged SKILL.md stops being a skill in the Agent Skills spec's own sense
— canonical instructions in the Markdown body — and becomes a pipeline
config file wearing a SKILL.md costume.

Resolution: every stage's prompt is the **full SKILL.md body, prepended,
followed by that stage's own authored `instructions`** as the specific
task/focus for this turn — not a replacement for the body, an addendum on
top of it. The body is small (a few hundred words) compared to what
actually caused the context-bloat bug (~70 accumulated tool results in
one turn), so resending it per stage is cheap and doesn't reintroduce the
problem staging exists to solve. This keeps the Markdown body the single
authoritative source of truth for what the skill is and what its
guardrails are — still genuinely a skill — while `stages` frontmatter
only adds turn-boundary and per-stage-focus metadata, the same kind of
declarative extension as `expected_outputs` or `tool_call_budgets`.

## 5. Engine orchestration mechanics

For a skill declaring `stages`, `engine/interactive.py`'s per-turn
handling (today: one `_run_turn` call per user prompt) is replaced by a
staged runner, roughly:

```python
async def _run_staged_skill(harness, tools, skill_body, stages, *, workspace_root, date):
    all_captures: list[tuple[str, str, Path]] = []
    stage_status: dict[str, bool] = {}   # stage id -> did its own `produces` land
    final_text = ""
    total_cost_usd = 0.0
    total_duration_ms = 0
    total_tokens = 0
    for stage in stages:
        needed = [
            skills.resolve_pattern(p, workspace_name=workspace_root.name, date=date)
            for p in stage.get("needs", [])
        ]
        present = [p for p in needed if p.exists()]
        missing = [p for p in needed if not p.exists()]
        # skill_body: the full SKILL.md body text (description, steps,
        # guardrails) -- shared context, prepended to every stage, not
        # extracted or trimmed per stage. See "The body is not replaced"
        # above.
        prompt = _build_stage_prompt(skill_body, stage, present=present, missing=missing)
        async with harness.open_session(tools) as session:   # fresh session -> fresh context
            text = ""
            async for chunk in session.send(prompt, workspace_root=workspace_root):
                text += chunk
            all_captures.extend(session.last_captures)
            final_text = text  # only the last stage's text is the actual digest
            for line in session.last_over_budget:
                print(f"[stage {stage['id']}] [budget] {line}")

        expected = [
            skills.resolve_pattern(p, workspace_name=workspace_root.name, date=date)
            for p in stage.get("produces", [])
        ]
        stage_status[stage["id"]] = all(p.exists() for p in expected) if expected else True

        # EngineResult.raw is the harness-native ResultMessage -- already
        # carries duration_ms / total_cost_usd / usage per SDK session, so
        # per-stage cost accounting is a read, not new instrumentation.
        raw = getattr(session.last_result, "raw", None)
        duration_ms = getattr(raw, "duration_ms", 0) or 0
        cost_usd = getattr(raw, "total_cost_usd", 0.0) or 0.0
        usage = getattr(raw, "usage", None) or {}
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        total_duration_ms += duration_ms
        total_cost_usd += cost_usd
        total_tokens += tokens

        print(f"[stage] {stage['id']}: "
              f"{'ok' if stage_status[stage['id']] else 'expected output missing'} "
              f"({duration_ms / 1000:.1f}s, ${cost_usd:.4f}, {tokens} tok)")

    print(f"[staged run total] {total_duration_ms / 1000:.1f}s, "
          f"${total_cost_usd:.4f}, {total_tokens} tok across {len(stages)} stages")
    return final_text, all_captures
```

**Per-stage reporting and cost accounting — decided (2026-08-07), together.**
§9 originally left both open separately. They resolve as one decision:
per-stage, not aggregate-only, because the harness-native `ResultMessage`
behind every `EngineResult` (`engine/harnesses/claude_agent_sdk.py`)
already carries `duration_ms`, `total_cost_usd`, and `usage` per session —
confirmed by reading `claude_agent_sdk/types.py`'s `ResultMessage` dataclass
directly — so reading it out per stage costs nothing new; the SDK is
already computing these numbers on every `open_session()`, staged or not.
The `[stage] ...` line (already sketched above) now also carries that
stage's own wall-clock/cost/tokens, and `_run_staged_skill` accumulates a
`[staged run total] ...` line printed once at the end — which is also what
finally answers §9's "cost accounting — not yet measured" question for
real: run a staged `morning-digest` once, read that one total line, and
compare it directly against the current single-turn run's own
`EngineResult.raw` numbers, instead of estimating "four handshakes plus
some orientation overhead" from first principles.

`missing` is what lets a downstream stage's prompt state plainly which
prior stage's output didn't show up (§9's fail-open decision) — the
engine knows this from `produces`/`needs` glob checks, not from catching
an exception, so it also covers a stage that returned normally but simply
didn't write what it was supposed to.

**`_build_stage_prompt`'s contents.** `needs` files are passed as
*paths*, for the stage's own session to `Read` if it actually needs their
contents — not inlined into the prompt. Inlining would quietly reopen the
exact problem staging exists to close: a `digest_{date}.json` or
`materiality_flags_{date}.json` is small today, but nothing bounds that
in general, and "just paste the JSON into the prompt" is precisely the
kind of context growth this design is trying to keep out of any one
turn. `present`/`missing` (from the `needs` check above) tell the model
which paths exist to read and which don't — never file contents.

**Order validation.** `stages` is a YAML sequence, so its list order is
the execution order — no separate numbering field on each stage entry.
(A hand-maintained `order: N` field would just be redundant bookkeeping
that can drift from the list's actual position, the same class of problem
the extraction-vs-authored decision in §4 was made to avoid.) What *is*
worth checking mechanically, at skill-load time alongside the rest of
`stages` parsing (`engine/skills.py`): walk the list once and confirm no
stage's `needs` names a file that only a stage at the same or later
position `produces`. This catches an authoring mistake — e.g.
`news_and_materiality` accidentally listed before `portfolio_and_market`
while still `need`-ing `digest_{date}.json` — as a load-time error, the
same way a malformed `expected_outputs` pattern would fail today, rather
than as a confusing missing-file gap discovered only when the pipeline
actually runs.

The critical, non-obvious detail: **stages must be fresh sessions, not
just fresh `send()` calls on one open session.** `ClaudeSession` /
`ClaudeSDKClient` is explicitly built to hold conversation state *across*
`send()` calls (`engine/harnesses/base.py`'s `Session` docstring: "holds
conversation state across calls to `send()`") — that's the entire point
of the session abstraction for ordinary multi-turn chat, and it means a
second `send()` on the same session does **not** reset accumulated
context. Only a new `ClaudeSDKClient` connection (`open_session()` again)
starts genuinely clean. This has a real cost: each stage re-pays MCP
server handshake (`_wait_for_mcp_servers_ready`, "a few real seconds" per
the existing docstring) — a few seconds per stage, four stages, against
avoiding a 31-minute run silently dropping a third of its own citations.
Worth it, but worth stating plainly since it's the main new runtime cost
this design adds.

## 6. Impact on existing mechanisms

- **`expected_outputs` / `match_changed_files`** — unchanged at the skill
  level (still the generic before/after file-diff check for the run as a
  whole). New at the stage level: each stage's own `produces` (§4) is the
  same check scoped to one stage, run right after that stage's session
  closes rather than once at the very end — this is what makes fail-open
  partial-failure handling (§8) mechanical instead of exception-based.
- **`deterministic_scripts` / typed SDK tools
  (`engine/skill_tools.py`)** — unchanged. Each stage's own session gets
  the same typed tools built today; nothing about `run_digest_math` /
  `run_surveillance_check` / `run_materiality_check` changes.
- **`tool_call_budgets` (`engine/tool_budget.py`)** — gets *simpler*, not
  more complex. A budget like `india_news.get_news: 25` is conceptually
  scoped to "one digest run's news-fetch step," which today has to share
  a turn with everything else. Under staging it lives entirely inside one
  stage's own session, so `TurnBudgetTracker.reset()` firing at the start
  of that stage's own `send()` is already exactly the right boundary —
  no change needed to `engine/tool_budget.py` itself.
- **Sources footer (`engine/sources_footer.py`)** — needs to move.
  Today `build_footer()` is called once, inside `ClaudeSession.send()`,
  from that one turn's own `captures`. Under staging there should be
  **one** footer, appended once after the final (compose) stage, built
  from *every* stage's captures concatenated — not a footer per stage.
  `build_footer()` itself doesn't need to change (it's already a
  standalone function taking a captures list); only the caller does — the
  staged runner accumulates `all_captures` across stages and calls
  `build_footer(all_captures, ...)` once, appending it to the final
  stage's text before the `.md` save.
- **`.md` autosave (`engine/interactive.py`'s
  `_save_composed_outputs`)** — mostly transfers unchanged, pointed at
  the final stage's text (which is the only stage that produces the
  actual composed digest) plus the now-aggregated footer, instead of one
  turn's full accumulated text.
- **Workspace-snapshot diffing
  (`engine/workspace.py`'s `snapshot_all`/`changed_since_all`)** —
  unchanged in mechanism; the staged runner just needs to snapshot once
  before the first stage and diff once after the last, same as today's
  single-turn `_run_turn`.

## 7. Applied to morning-digest (worked sketch)

Given the `stages` block in §4, a run would look like:

1. **`portfolio_and_market`** (fresh session): holdings, live quotes,
   `run_digest_math`. Produces `results/digest_<date>.json`. Nothing
   about the other stages needs to be in this stage's context at all.
2. **`surveillance`** (fresh session, told only "Stage 2 of
   morning-digest; digest is at `results/digest_<date>.json` if you need
   it" — in practice this stage doesn't even need it): ASM/GSM lists,
   `run_surveillance_check`. Produces `results/surveillance_flags_<date>.json`.
3. **`news_and_materiality`** (fresh session, told "read
   `results/digest_<date>.json` for today's bounded symbol set"): the
   18×`get_announcements` + 18×`get_news` calls that were the ones
   losing captures live entirely in a stage whose *starting* context is
   just the digest's short computed summary, not the full holdings/quotes
   history that produced it. `run_materiality_check`. Produces
   `results/materiality_flags_<date>.json`.
4. **`compose`** (fresh session, told to read all three result files):
   composes the actual brief. This stage's text is what gets the
   aggregated Sources footer appended and gets `.md`-saved.

This directly targets the confirmed failure condition (§1): the stage
that made 29 calls and lost 11 of them would now start from a
few-hundred-token prompt plus one short JSON file, not from ~40 prior
tool results' worth of accumulated context.

## 8. Routing — how a staged skill's run actually gets triggered

Found by re-checking this design against the actual `engine/interactive.py`
code (`_repl`, `_run_turn`) rather than against the pseudocode in §5 alone.
This turned out to be more foundational than the §9 open questions —
the rest of this doc quietly assumed it away — and went through three
candidate resolutions before landing on one. Recorded in order, because
the reasoning for rejecting the first two is exactly what justifies the
third, not just historical color.

**The core problem.** Today, `_repl` opens one session with *all*
configured skills available as tools (`tools.skills`, the full static
list from `build_tool_config()`) and calls `_run_turn(session, prompt,
...)`. Which skill actually applies to a given prompt — "run morning
digest," "show results of morning digest," "what happened overnight" are
all the same intent, differently worded — is decided by the model itself,
mid-turn, via the SDK's native `Skill`-invocation mechanism. There is no
reliable *non*-model way to resolve that: matching arbitrary natural-
language paraphrases to the right skill is a language-understanding
problem, not a lookup, and no keyword or regex rule generalizes across it
without becoming exactly the brittle, hand-maintained pattern-matching
this project avoids everywhere else. So the engine cannot know, ahead of
a turn, which skill (if any) a prompt targets — but `_run_staged_skill`
(§5) needs to know that, and know it declares `stages`, *before* opening
stage 1's session.

**Candidate 1 — an upfront routing turn.** A cheap, tool-less
classification call ("which skill, if any, does this map to?") before
deciding whether to call `_run_turn` or `_run_staged_skill`. **Rejected:**
since there's no cheaper reliable way to answer "which skill?" than
asking Claude, this duplicates work the model's native `Skill` mechanism
already does — the same question gets asked twice, adding latency to
*every* prompt, staged or not, just to re-derive an answer the real turn
would have produced anyway.

**Candidate 2 — intercept the model's native `Skill` tool call via a
`PreToolUse` hook.** Let the model's normal `Skill`-invocation happen for
turn 1 as it does today (this is the one thing the model already does
reliably — no evidence it mis-selects skills, unlike the Sources footer,
the `.md` save, or the news-duplication bug, all confirmed-unreliable
prose instructions). A third `PreToolUse` hook, alongside the existing
order-tool and Bash-scope ones in `claude_agent_sdk.py`, would fire when
the model calls `Skill(name="morning-digest")`, check whether that skill
declares `stages`, and deny the call if so — the interactive loop treats
the denial as the redirect signal and switches to `_run_staged_skill`.

Confirmed technically real (the SDK's own internals list a literal
`"Skill"` tool, so it is hookable the same way `place_order` and
out-of-scope `Bash` already are) — but walking the actual flow surfaced
two real costs, not just theoretical ones:
- `_run_turn` streams output live (`print(chunk, end="", flush=True)`),
  not buffered. Whatever text the model produces *after* being denied —
  some kind of "I'm unable to do that" — would already be on the user's
  screen before the engine can act on the redirect, a confusing flicker
  right before the real staged digest starts.
- The denied `Skill` call and whatever text followed it stay in the
  REPL's ongoing session history permanently — small, but genuinely
  useless pollution, not the digest's own content.

**Rejected** in favor of candidate 3, once it became clear a tool-based
approach avoids both costs rather than just tolerating them.

**Candidate 3 — decided: expose a staged skill as a dedicated in-process
SDK tool, not through the `Skill` mechanism at all.** `engine/skill_tools.py`
already establishes this exact pattern for `run_digest_math` etc.: an
in-process SDK MCP server built via `create_sdk_mcp_server`, running in
the *same Python process* as the rest of the engine — not a separate
`mcp/*/server.py` subprocess needing its own credentials. A staged skill
gets one dedicated tool built the same way — `run_staged_morning_digest`
— whose name and description are generated from that skill's own
frontmatter (reusing the exact `description` text already authored for
skill matching, so routing quality doesn't regress) and whose handler
runs the real `_run_staged_skill` pipeline, opening a fresh session per
stage, then returns the finished digest as an ordinary tool result.

This resolves the routing problem without needing to predict or
intercept anything: the model calling this tool *is* the routing
decision, made the normal, already-reliable way (tool selection by
description, the same mechanism behind every other tool call this
project already trusts), not a special case requiring a hook.

It also eliminates both of candidate 2's costs, rather than trading them
for new ones: the tool call just succeeds, like any other tool — no
denial, no streamed "I can't do that" text, and the outer REPL session's
history gains one clean, useful exchange (the finished digest) instead of
a denied call plus whatever confused text followed it. And progress
visibility isn't lost either: because this is an *in-process* tool (not a
subprocess across an RPC boundary), the handler can `print()` the
`[stage] ...` diagnostics (§9) directly to the same terminal in real
time, exactly as `_run_staged_skill` would if `_repl` called it directly.

**As a side effect, this also resolves the second integration gap this
section originally raised** — what happens to `_repl`'s single
long-lived session after a staged run. It's moot under candidate 3: the
outer session is never torn down or replaced, it just receives one more
(bounded, useful) tool result, the same as any other tool call today.
Follow-up questions ("why is RELIANCE flagged?") have that content
sitting right in the session's own history — no session-promotion logic
needed.

**What candidate 3 requires to actually be reliable, not just plausible:**

- **A `stages`-declaring skill must be exposed *only* through this tool —
  never also registered in `tools.skills` for native `Skill`-invocation.**
  If both paths existed side by side, the model would have to reliably
  *prefer* the tool over reading the skill body itself — the same
  prose-reliance failure this whole design exists to avoid. One entry
  point, no competing path, no judgment call for the model to get wrong.
- **The `.md` autosave and Sources footer must be written by the tool
  handler itself, not by `_run_turn`'s post-processing.** Today's save
  logic (`_save_composed_outputs`) works off the outer turn's own
  streamed chunks; if the real digest text now arrives as a tool result,
  trusting the outer model to paste that result back verbatim as its own
  final response would just be a new instance of the same prose-reliance
  risk. The handler — plain engine Python, not a model — does the save
  directly.
- **Confirmed live (2026-08-07).** A throwaway script
  (`verify_nested_session.py`, scratchpad, not part of the repo)
  registered an in-process SDK tool whose handler opens a second,
  independent `harness.open_session(...)` — a genuinely separate
  `ClaudeSDKClient` — while the *outer* session's own client sat mid-turn
  awaiting that exact tool call. The nested session opened, exchanged a
  real message, and closed cleanly; the tool handler returned its result;
  the outer turn completed normally (`last_result.ok == True`) with the
  nested reply folded into its own response. A second turn sent on the
  *same* outer session afterward also completed normally
  (`last_result.ok == True`), confirming the outer session wasn't left in
  a corrupted state by the nesting. No deadlock, no crash, no shared-state
  interference — the mechanism candidate 3 depends on is real.

**Differentiating staged-workflow tools from ordinary ones.** Since these
are conceptually different from `run_digest_math`-style tools (long-
running, many internal sub-calls, one final result — not a quick
synchronous computation), a few concrete, code-grounded ways to mark that
distinction:
- **A separate in-process server**, e.g. `create_sdk_mcp_server(name=
  "staged_workflows", tools=[...])`, distinct from the existing
  `"skill_scripts"` server. This gives every staged-workflow tool a
  distinct namespace in the model's own tool list
  (`mcp__staged_workflows__run_staged_morning_digest`), and — more
  usefully — plugs into addressing this project already has:
  `engine/tool_capture.py`'s `parse_mcp_tool_name` and
  `engine/tool_budget.py`'s `TurnBudgetTracker` both already key off
  `(server, tool)` pairs, so any future engine logic that wants to treat
  staged workflows as a category can just check `server ==
  "staged_workflows"`, no new bookkeeping.
- **Explicit framing in the tool's own description** — the part that
  actually shapes model behavior, same mechanism already relied on for
  routing quality everywhere else: e.g. "Multi-stage background workflow.
  Takes several minutes, makes many internal sub-calls, returns one final
  result. Call once; don't call repeatedly or expect intermediate
  output."
- **A naming convention on the tool name itself**, mirroring the existing
  `run_<script_id>` pattern for deterministic scripts — `run_staged_
  <skill_name>` — visible in any tool listing without needing annotation
  support at all.
- **SDK tool annotations exist and are real** — confirmed directly in the
  installed `claude_agent_sdk` package: `SdkMcpTool`/`tool()` accept an
  `annotations: ToolAnnotations` parameter backed by the actual MCP-spec
  type (`title`, `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`). Worth using — `openWorldHint: true` genuinely applies,
  and `title` can carry a human-readable label — but the spec has no
  purpose-built "this is a long-running workflow" hint, so this is a
  secondary, nice-to-have layer, not the load-bearing signal (the
  description text is).

## 9. Open questions / risks

- **Extraction vs. authored prompts** (§4) — **Decided (2026-08-05):**
  authored, in frontmatter. See §4.
- **Partial-stage failure** — **Decided (2026-08-05):** fail open, note
  the gap — same pattern already used for NSE circuit-open in
  `surveillance_check.py`. Mechanically, this is what each stage's own
  `produces` field (§4) is for: right after a stage's session closes,
  `_run_staged_skill` (§5) checks its declared `produces` files against
  disk — the same glob check `expected_outputs` already uses — and records
  pass/fail per stage regardless of whether the stage raised. The next
  stage's prompt is then built from that record, explicitly listing which
  `needs` files are present vs. missing — not assuming every prior stage
  succeeded. The `compose` stage's authored `instructions` (§4) already
  says "any file missing from the list means that stage failed — say so
  explicitly," but it's the engine's `produces` check that supplies the
  ground truth, not compose's own discovery. A stage whose own run raises
  an exception is treated identically to one whose `produces` files just
  didn't show up: recorded as failed, its outputs absent for every later
  stage, pipeline continues.
- **Per-stage vs. aggregate turn reporting** — **Decided (2026-08-07):**
  per-stage. Today's `[matches ...]` / `[engine saved ...]` / `[budget
  ...]` console diagnostics are printed once per turn; under staging, each
  stage prints its own `[stage {id}] [budget] ...` lines and a `[stage]
  {id}: ok/expected output missing (...)` summary as it finishes, plus one
  `[staged run total]` line at the very end. See §5.
- **Does this fully eliminate the capture-loss bug, or just make it much
  less likely?** The hypothesis in §1 is context size correlating with
  the failure, not a proven threshold. Each stage is far smaller than the
  full digest, but `news_and_materiality` alone still makes up to
  ~36 calls (18 announcements + 18 news) in one turn — worth a targeted
  repro at that stage's actual scale before declaring this solved, not
  just assumed from the general trend.
- **Cost accounting** — **Decided (2026-08-07):** instrumented, not
  estimated. Four sessions instead of one means four MCP handshakes and,
  likely, some repeated model "orientation" overhead per stage
  (re-establishing what workspace/task it's in) — the concern was real,
  but rather than guess at its size, `_run_staged_skill` (§5) now reads
  each stage's actual `duration_ms` / `total_cost_usd` / `usage` straight
  off the SDK's own `ResultMessage` (already computed per session, staged
  or not) and prints a `[staged run total]` line. Whether the overhead
  turns out to be large is now a one-run measurement against the current
  single-turn baseline, not an open question — see step 1 of §10.
- **Resumability — explicitly out of scope for v1.** Each stage's
  `produces` file (§4) is a natural checkpoint, which raises an obvious
  question this doc isn't answering yet: should a re-run skip a stage
  whose `produces` file already exists for today's date, instead of
  redoing it? Not addressed — v1 always runs all four stages on every
  invocation, no skip-if-exists logic. Resumability is a real feature
  with its own edge cases (stale vs. intentionally-refreshed same-day
  data) and isn't needed to fix the capture-loss bug that motivated this
  design; revisit separately if it turns out to matter in practice.

## 10. Rollout plan (proposed, not started)

0. ~~Verify §8's one remaining unconfirmed technical detail...~~ **Done,
   2026-08-07** — confirmed live, nested sessions are safe. See §8.
1. ~~Prototype `stages` and the `run_staged_morning_digest` tool against
   `morning-digest` only...~~ **Built, 2026-08-07** — structurally, not yet
   live-verified (that's step 2, next). What landed:
   - `ToolConfig.include_staged_tools` (`engine/harnesses/base.py`) — the
     recursion guard from §8's requirements.
   - `engine/skills.py`: `load_stages` (+ load-time order validation, §5),
     `load_skill_body`, `load_description`.
   - `engine/staged_skills.py` (new): `run_staged_skill` (§5's
     `_run_staged_skill`, real per-stage cost/duration/token accounting
     and fail-open `needs`/`produces` checks) and `compose_and_save`
     (§8's second requirement — the engine, not the outer model, writes
     the aggregated Sources footer and the `.md` output).
   - `engine/staged_skill_tools.py` (new): builds `run_staged_<skill>` on
     its own `staged_workflows` in-process server (§8's differentiation
     subsection — separate namespace, `openWorldHint`/`idempotentHint`
     annotations, explicit "multi-stage background workflow" framing in
     the description).
   - `engine/harnesses/claude_agent_sdk.py`'s `_build_options`: a skill
     declaring `stages` is now filtered out of the native `skills=` list
     and gets `staged_workflows` registered instead — §8's first
     requirement (one entry point, never both).
   - `.claude/skills/morning-digest/SKILL.md`: real `stages:` frontmatter
     for all four stages from §7's worked sketch (the `compose` stage
     declares no `produces` — its output is written by
     `compose_and_save`, not a deterministic script inside that stage's
     own session, so there's nothing to mechanically check the instant
     that stage's session closes).
   - 14 new tests (`tests/test_engine_staged_skills.py`,
     `tests/test_engine_staged_skill_tools.py`) plus 3 new + 1 updated
     test in `tests/test_engine_claude_harness.py` — all against fakes,
     same precedent as the rest of this test suite; 264 passed, `ruff
     check` clean.
   - **Not done here:** no real `ClaudeSDKClient`/Kite call. Structural
     wiring only — step 2 is the live pass.
2. ~~Live-verify specifically against a large-portfolio account...~~
   **Done, 2026-08-07** — ran `run_staged_morning_digest` for real against
   the live QK0438 account (96 holdings that day) in a fresh
   `staged-digest-live-verify` workspace. All four stages completed ok:
   portfolio_and_market (187.7s, $0.9442, 9928 tok), surveillance (182.7s,
   $0.3462, 3978 tok), news_and_materiality (149.4s, $1.2959, 5447 tok),
   compose (57.0s, $0.4167, 5146 tok) — 576.9s (~9.6 min) total, $3.0029,
   24,499 tokens across 4 fresh-context sessions. Pass/fail bar per this
   step's own criterion: diffed the 46 `data/*.json` basenames actually on
   disk against the 46 files cited in the composed digest's Sources
   footer — exact match, zero missing, zero phantom. The bounded
   news/materiality set (20 symbols × `get_announcements` +
   `india_news.get_news` = 40 calls) all landed in captures cleanly, no
   sign of the original 29-calls/18-captured drop. Also ~3x faster
   wall-clock than the original single-turn run (~9.6 min vs. ~31 min).
   Output: `workspaces/staged-digest-live-verify/results/digest_2026-08-07.md`.
3. ~~Only after that's proven: generalize `stages` handling and the
   staged-workflow-tool builder...~~ **Done, 2026-08-08.** Turned out the
   generalization work was already done as a side effect of how step 1 was
   built: `engine/staged_skills.py` and `engine/staged_skill_tools.py`
   were written generic from the start — the only per-skill input either
   module ever takes is a `skill_name` string used to read that skill's
   own frontmatter, with no comparison against `"morning-digest"`
   anywhere in either file (both modules' own docstrings say so
   explicitly) — and they already live as sibling modules, the
   parenthetical alternative this step itself allowed for. `_build_options`
   (`engine/harnesses/claude_agent_sdk.py`) also already loops over every
   configured skill computing `skills.load_stages(name)` per name, not
   just morning-digest's. What step 3 actually still needed:
   - **Proof, not just an unverified claim.** Added
     `test_build_options_routes_any_stages_declaring_skill_not_just_morning_digest`
     (`tests/test_engine_claude_harness.py`) and
     `test_staged_tool_generalizes_to_any_stages_declaring_skill_not_just_morning_digest`
     (`tests/test_engine_staged_skill_tools.py`) — each builds a synthetic
     `widget-digest` skill under a monkeypatched `SKILLS_ROOT` with its
     own `stages` block and confirms it gets identical routing and a
     correctly named/described `run_staged_widget_digest` tool. 266
     passed (up from 264), `ruff check` clean.
   - **Docs.** `docs/vision.md` §4's Architecture section now has a
     `stages` paragraph (what it is, why it exists, how it's exposed,
     live-verification pointer). `docs/skills.md`'s template gained a
     "Staged? (optional)" line explaining when a future skill should reach
     for this and what it needs to declare.

Steps 0 through 3 are all done. §9's two gating decisions (extraction-vs-
authored-prompts, partial-stage-failure handling) were made 2026-08-05 —
authored frontmatter prompts, fail-open with an explicit gap note. §8's
routing question is decided — staged skills are exposed as dedicated
in-process SDK tools (§8, candidate 3), not through the native `Skill`
mechanism — and its one technical precondition (nested-session safety)
was confirmed live 2026-08-07 (step 0). Step 1's prototype (`stages`
parsing, `run_staged_morning_digest`, the `staged_workflows` server, real
morning-digest `stages` frontmatter) was built and passing its own test
suite (2026-08-07), then step 2 exercised it for real against the live
QK0438 account the same day, then step 3 confirmed (with a second,
synthetic skill) that none of it was secretly morning-digest-specific and
documented the field in `docs/vision.md`/`docs/skills.md` (2026-08-08).
The staging approach directly fixed the bug this doc opened with: an
exact 46/46 match between the Sources footer and the files actually on
disk, where the original single-turn run dropped 11 of 29. The only §9
items still open — whether staging fully eliminates the capture-loss bug
across *every* possible run, not just this one; resumability — were
already flagged as not blocking rollout and remain genuinely open,
revisit if either turns out to matter in practice. Nothing in this doc's
rollout plan is currently pending.
