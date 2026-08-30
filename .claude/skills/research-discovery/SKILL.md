---
name: research-discovery
description: Use when the user has an open-ended research question that doesn't map cleanly to one existing skill — a headline, a tip, a vague hunch, or a cross-cutting question with no single sector/symbol ("what's driving FII outflows", "PLI scheme beneficiaries", "should I be worried about X given the rupee"). Not for a request that already names a clean sector (use screen-indian-stocks), a specific stock needing a governance check or thesis update (use red-flag-scan/thesis-tracker), or a portfolio-wide review (use portfolio-health-check).
expected_outputs: []
---

# Research Discovery

The front door for research that doesn't already know its own shape. This
skill never produces the final brief itself — it clarifies scope, checks
what's already known, plans a small set of angles, and hands off to
`research-discovery-gather` (a separate, staged-only skill) to actually
fetch and synthesize. See `docs/research-discovery-plan.md` §1 for why
this is two skills, not one: a staged run can't pause mid-way to ask the
user anything, and has no way to receive this turn's own request content
— both confirmed directly from `engine/staged_skill_tools.py`. Everything
in this skill runs as one ordinary, multi-turn-capable session, same as
`thesis-tracker`.

This skill never touches Kite — no account-identity check needed, same
reasoning as `screen-indian-stocks`.

## Steps

1. **Clarify — only if genuinely ambiguous.** Ask **at most one** scoping
   question, and only when two reasonable interpretations of the request
   would lead to meaningfully different work (docs/research-discovery-
   experience.md §4's test: "would two different reasonable
   interpretations lead to meaningfully different work — not "is this
   vague"). Examples:
   - "Just read India's PLI scheme for semiconductors got a new funding
     tranche" — genuinely ambiguous (pure-play names only, or the wider
     supply chain too? quick curiosity, or building toward a position?) —
     ask one question.
   - "What's driving the market down this week" — only one reasonable
     reading — proceed directly, no question.
   If the user's answer is still vague ("whatever you think is useful"),
   proceed on your own best-reasoned interpretation and state plainly
   which interpretation you used — don't ask a second time.

2. **Check the workspace before doing any fresh work.** Use `Glob` to list
   `research/sectors/*.md`, `research/stocks/*.md`, `research/themes/*.md`,
   and `theses/*.md`, then `Read` any file that looks relevant to this
   request's subject. Also `Read` `notes.md` if it exists. If something
   relevant is already there, lead with it in your eventual reply ("You
   already have a research note on this from three weeks ago — here's
   what's changed") rather than silently re-running everything from
   scratch — carry forward whatever's still current as this run's
   `already_known` (step 4).

3. **Identify up to 6 fresh angles.** For each angle worth pursuing that
   step 2 didn't already answer, note: a short id (lowercase, hyphenated,
   e.g. `policy-context`, `company-exposure`), the specific question it's
   trying to answer, and which MCP tool(s) it likely needs (e.g.
   `india_news.get_news`, `india_screener.get_fundamentals`,
   `india_filings.get_fii_dii_flows`, `india_macro.get_policy_rates`). If
   more than 6 genuinely relevant angles surface, state plainly which got
   deprioritized and why — never drop one silently. An angle already fully
   answered by step 2's workspace check doesn't need a fresh gather pass;
   don't include it here.

4. **Write the plan, then hand off.** Build a slug for this run the same
   way `screen-indian-stocks` slugs an industry label — lowercase, hyphens
   for non-alphanumeric runs, e.g. `pli-semiconductors`. Call
   `update_workspace_notes` with `target` set to
   `data/research_plan_<slug>_<date>.json` (today's date, `YYYY-MM-DD`)
   and `content` set to this exact JSON shape:

   ```json
   {
     "request": "<the clarified request, in your own words>",
     "already_known": ["<one-line summary per relevant existing file found in step 2>"],
     "angles": [
       {"id": "<short-id>", "question": "<the angle's question>", "tool_hint": "<tool name(s), or omit if unclear>"}
     ]
   }
   ```

   Then call `run_staged_research-discovery-gather` with `workspace_root`
   set to the exact active-workspace path. That tool runs for a while (it
   opens several fresh internal sessions, one per angle, then composes and
   saves the result) and returns the finished brief as its own text —
   **relay that text back to the user verbatim as this turn's reply.**
   Don't re-narrate, summarize, or add your own framing on top of it; the
   gather/synthesize skill already writes it as the actual deliverable,
   composes it with the engine's own Sources footer and SEBI disclaimer,
   and saves it to the workspace.

## Guardrails

- Never call Kite's order-placing/modifying tools — not applicable to
  this skill (it doesn't touch Kite at all), but the rule holds
  project-wide.
- **One clarifying question maximum**, and only when genuinely needed —
  see step 1's test. Don't ask as a default courtesy before an already-
  crisp request; a request that already names a clean sector or symbol
  never reaches this skill in the first place (see this skill's own
  `description` above).
- Never invent a finding you can't source — if step 2 or the eventual
  gather/synthesize result comes back with a real gap, say so plainly
  rather than filling it in from general knowledge.
- Don't write your own version of the final brief — that's `research-
  discovery-gather`'s `synthesize` stage's job. This skill's own reply,
  once the handoff happens, is that tool's returned text, not a new
  composition.
- `data/research_plan_<slug>_<date>.json` is the only new file this skill
  writes directly (via `update_workspace_notes`) — never `Write` it by
  hand, and never write into any `research/` bucket file yourself; that's
  `synthesize`'s job once real findings exist to file.
