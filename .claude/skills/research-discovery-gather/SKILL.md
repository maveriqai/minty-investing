---
name: research-discovery-gather
description: Staged back half of research-discovery — never invoked directly by name or native routing; only reachable via the run_staged_research-discovery-gather tool, which research-discovery's own step 4 calls after writing a plan file. Not a skill a user request should ever be matched to.
expected_outputs: []
# No engine-auto-composed .md/.json artifact of its own (see the note
# below on why) — the run's real durable output is whichever
# research/<bucket>/<slug>.md file(s) the synthesize stage writes via
# update_workspace_notes, a real tool call inside that stage's own
# session, not something the engine composes generically afterward.
# compose_and_save (engine/staged_skills.py) still unconditionally appends
# the Sources footer + SEBI disclaimer to the text this run returns,
# regardless of expected_outputs being empty — only the "also write a
# separate file to disk" half of compose_and_save is a no-op here.
stages:
  # dynamic: true (docs/research-discovery-plan.md §4) — not a stage with
  # its own fixed instructions. run_staged_skill reads the plan file
  # `needs` points at (written by research-discovery's step 4, a separate,
  # earlier turn — not a prior stage of *this* run, which is why its
  # freshness check is a plain existence check, not the run-start-relative
  # one `needs`/`produces` normally use), and expands it into one stage
  # instance per angle (up to max_instances), each with its own generated
  # instructions built from that angle's own question/tool_hint. Fail-open
  # per instance: one angle's session not writing its finding file doesn't
  # cancel the other angles or abort the run — only synthesize below can
  # abort this run, since only it is critical.
  - id: gather
    dynamic: true
    needs:
      - "{workspace}/data/research_plan_*_{date}.json"
    produces:
      - "{workspace}/data/research_finding_*_{date}.json"
    max_instances: 6
  - id: synthesize
    critical: true
    instructions: |
      This is the final stage of a research-discovery run. Find this
      run's research_finding_*.json and research_plan_*.json files
      yourself (the exact finding count varies run to run — don't assume
      a fixed number, and don't rely on any needs/produces listing above
      naming them individually): call Glob with `path` set to the active
      workspace's own `data` subdirectory (the workspace path is in the
      "[Active workspace: ...]" note above this text — append `/data` to
      it yourself) and `pattern` set to the bare filename glob
      `research_finding_*.json` — **do not combine the `data/` segment
      into the pattern string itself** (e.g. `pattern="data/research_finding_*.json"`
      with `path` set to the workspace root). That combination, and a
      relative pattern with no `path` argument at all, have both been
      live-verified to silently return zero matches even when the files
      exist — `path` must point directly at the `data` directory, `pattern`
      must be filename-only. Read every file that Glob call returns. Then
      do the same for the plan file — `path` = the workspace's `data`
      directory, `pattern` = `research_plan_*.json` — and Read it for its
      "request" and "already_known" fields; you need the original request
      in your own words to know what this brief is actually answering.

      Compose one coherent brief, organized by angle (not five findings
      concatenated with headers) — for each angle, state what it answered,
      cite which tool/source it came from, and if that angle's finding
      file is missing, say so plainly as a real gap rather than guessing
      or silently omitting the angle. Blend in the plan's "already_known"
      material where relevant rather than re-deriving it.

      Decide which research/ bucket(s) this belongs in — research/sectors/
      for an industry-wide subject, research/stocks/ for a single-symbol
      subject, research/themes/ for a cross-cutting theme that doesn't
      reduce to one sector or stock — and call update_workspace_notes once
      per bucket that applies (most runs need only one; a pass that
      genuinely spans e.g. a theme and a specific holding's relevance may
      need two). Use a lowercase-hyphenated slug for research/sectors/ and
      research/themes/ targets (matching the plan file's own slug), and an
      uppercase symbol for research/stocks/ targets. Read the target file
      first if it already exists (the workspace check in research-
      discovery's step 2 may have already surfaced it) and merge your
      update into it — don't overwrite prior content. Merge under a `##
      Findings` heading specifically: append a new dated entry (today's
      date, then this run's brief) rather than replacing the file, and
      create the heading if the file is new. `screen-indian-stocks` and
      `red-flag-scan` also write into these same sector/stock bucket
      files, under their own `## Screen History` / `## Red-Flag Checks` /
      `## Observations` headings (docs/research-notes-design.md §2.3) —
      leave those sections untouched if present, never rewrite the whole
      file even when it already has sections you don't recognize.

      Your reply text for this stage *is* the actual deliverable the user
      sees (research-discovery's step 4 relays it verbatim) — write the
      full brief here, not a report about what you did. Don't write your
      own Sources footer or SEBI disclaimer; the engine appends both
      automatically once this stage's text is complete.
    produces:
      - "{workspace}/research/**/*.md"
---

# Research Discovery — Gather & Synthesize

Never invoked by name — see this file's own `description` above. The only
entry point is `research-discovery`'s step 4, which writes
`data/research_plan_<slug>_<date>.json` and then calls
`run_staged_research-discovery-gather`. See docs/research-discovery-plan.md
§3 for the design (the `dynamic: true` gather stage, and why `synthesize`
globs its own inputs rather than relying on a fixed `needs` list).

No `## Steps` section in the usual sense — this file's body is shared
context every stage's session receives (per `engine/staged_skills.py`'s
`_build_stage_prompt`), and each stage's own behavior is fully specified by
its `stages` frontmatter above: `gather`'s instances are generated
per-angle at runtime from the plan file, and `synthesize`'s own
`instructions` are already the complete spec for that stage.

## Guardrails

- Never call Kite's order-placing/modifying tools — not applicable to this
  skill (it doesn't touch Kite at all), but the rule holds project-wide.
- A `gather` instance may only report what it actually found via a real
  tool call this stage — never fill in a finding from general knowledge
  because the angle "seems obvious." If a tool call fails or returns
  nothing useful, write that as the finding (`{"angle_id": "...", "status":
  "no_data", "detail": "..."}`), don't fabricate a plausible-sounding one.
- `synthesize` must report every angle whose finding file is missing as an
  explicit gap — never silently drop an angle from the brief.
- `synthesize` writes to `research/sectors|stocks|themes/<key>.md` only via
  `update_workspace_notes` — never `Write` directly, and never invent a
  bucket/key outside that allow-listed shape.
- This skill has no deterministic-script step — every figure a `gather`
  instance reports must trace to a real tool result it saw this stage, the
  same grounding discipline every other skill's narrated numbers already
  follow.
