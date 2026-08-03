# Minty v2 — Vision & Scope (working draft)

## 1. Problem & Audience

**Who it's for:** Indian retail equity investors who self-direct their own
trades via Zerodha, do their own research, and want serious daily support
without paying for institutional tools or handing decisions to a black-box
"recommendation" engine.

**The problem:** today this investor either does scattered manual research
— news, filings, price checks, FII/DII flows — across a dozen tabs with
nothing carrying over from one day to the next, or trusts an opaque tool
whose reasoning they can't audit and whose numbers they can't verify.
Neither compounds, and neither is fully trustworthy with a real brokerage
account connected.

**Why Minty:** a local-first research notebook (the Obsidian-for-investing
framing) that (a) actually remembers — findings from one session inform the
next instead of starting cold, (b) is grounded — every number comes from a
real tool call, never model memory, (c) is safe to connect a real account
to — order execution is structurally impossible, not just a policy promise,
and (d) is not a hosted service with your financial data on someone else's
server.

**Why now:** agent tooling — Claude's own tool-calling plus MCP, and
Zerodha shipping its own Kite MCP server — only recently got reliable
enough to build this without a mountain of custom broker-integration and
parsing code. And it exists because building it for real, against a real
portfolio, is what proved the compounding-notebook idea actually works day
to day, not just sounds good on paper.

## 2. What Minty v1 Does

### Track 1 — Minty as a standalone product

- User runs Minty's own entrypoint — a real interactive, multi-turn
  session, not "open Claude Code in this repo." This is the one true
  precondition for Track 1 existing at all.
- Connects their real Zerodha account through the Kite gateway — read-only
  by construction, not by policy alone: the six order-placing tools are
  never registered in the tool surface the model sees.
- LLM backend is configurable through a thin Harness seam. Claude is the
  one working implementation for v1; the seam exists so a second backend
  (Codex, named as the example) can be added later without a redesign — not
  built for v1, just not architecturally foreclosed.
- Core research capabilities available conversationally, on demand (see
  `docs/skills.md` for detail):
  - **v1 must-haves:** morning-digest, portfolio-health-check,
    red-flag-scan
  - **later:** screen-indian-stocks, thesis-tracker
  - **dropped:** refresh-holdings — superseded by the manual-trigger
    decision below; an interactive session can always complete Kite's
    login itself, so there's no headless-OAuth gap left to work around.
- A local, compounding workspace — notes and findings persist across
  sessions, so the fifth conversation already knows what the first one
  learned. The actual differentiator over asking any LLM the same question
  cold.
- Every output is grounded: numbers come from a real tool call or computed
  file, never model memory, with a Sources footer and the SEBI disclaimer
  attached automatically.
- **Digest delivery model: manual trigger + automated reminder, not a
  fully unattended pipeline.** A lightweight scheduled OS notification (no
  agent involved) nudges the user each morning; the digest itself is always
  generated on-demand through the same interactive capability as any other
  Track 1 conversation. This deliberately replaces the old repo's
  unattended `launchd` pipeline, which was both its biggest complexity
  source and its least reliable piece (headless OAuth limitations, an
  unresolved async-generator crash, a critic-gate needed only because
  nobody was watching the output live). Splitting "notify" (trivial, no
  agent) from "generate" (agent-driven, always interactive) removes that
  entire failure class rather than fixing it in place.

### Track 2 — Minty as a codebase people contribute to

- Clone the repo, follow one Getting Started doc, running locally in
  minutes.
- Add a new skill by following a documented template/spec (see
  `docs/skills.md`) — a clear "here's what a good skill PR looks like," not
  tribal knowledge.
- Add a new data source by following the existing Layer 2 MCP server
  pattern (one directory, one `server.py`, shared fetch/cache/rate-limit
  helpers).
- CI runs tests and lint automatically on every PR.

## 3. Explicit Non-Goals

**Out of scope for v1 (revisit later, not now):**
- Packaged app / GUI (Tauri or similar) — v1 is a conversational tool run
  from a terminal, nothing more.
- **A second LLM backend actually working — explicitly v1.1, not
  "someday."** Motivation is concrete, not optionality for its own sake:
  someone in the target early-user/contributor group may already have a
  Codex/ChatGPT subscription and not a Claude one, and being able to try
  Minty without buying a new subscription meaningfully widens who can
  actually take the first step. The Harness seam
  (`engine/harnesses/base.py`-equivalent) exists so this isn't
  architecturally foreclosed, but it is real, separate work, not a config
  swap — each of these has to be redone per backend, not shared: (a)
  auth — Claude's path (reuse an existing subscription login) was
  live-verified; Codex's guardrail equivalent was only ever
  config-confirmed, never proven against a live agent turn, and Minty's
  trust story specifically requires the latter; (b) skill loading — Claude
  gets this for free from the Agent SDK's own primitive, Codex has no
  designed equivalent yet; (c) multi-turn session support — built once for
  Claude's SDK, doesn't transfer, has to be built again for Codex's own
  SDK. Sequenced deliberately **after** Track 1 is solid on Claude alone —
  doing the hardest parts of Track 1 twice before the first backend is
  proven once is exactly the kind of scope creep this rebuild exists to
  avoid. **Gated on real signal, not a committed timeline:** top of the
  v1.1 backlog, first candidate to build once Track 1 ships — but only
  triggered by an actual early user or contributor saying they'd use Minty
  if it didn't require Claude specifically. Right now that's a hypothesis,
  not a confirmed blocker; committing engineering time to it before v1 has
  real usage means building on a guess, at the exact moment attention
  should be on what real users actually get stuck on. (Codex was already
  built once in the old repo and then explicitly retired — reviving it
  fast, before the audience gap is confirmed real, risks the same churn.)
- Multi-broker support. Zerodha/Kite only for v1. Layer 2 data tools stay
  broker-agnostic by convention (symbols/sectors in, never a
  Kite-specific shape out), so adding a second broker later touches
  Layer 1 only, not a rewrite.
- A public skill marketplace or auto-merged contributor skills. Track 2
  covers "how to propose a skill" via PR review — not an open gallery.
- **RAG / vector-search memory.** "Memory" itself is already core to v1 —
  the compounding workspace (§2/§4: plain markdown notes, read at the start
  of relevant work) — but semantic/vector retrieval over a larger corpus
  is not. The old repo's own convention deliberately caps workspace notes
  at ~2,000 words and says "summarize, don't duplicate" specifically so a
  note always fits directly in context, no retrieval step needed — and
  that constraint already proved itself (the compounding exit criterion was
  met with exactly this plain-file approach, zero embeddings). Building a
  RAG pipeline now — embeddings, chunking, retrieval tuning — would be
  solving a scaling problem before it exists. Same reasoning applies to
  automatic memory extraction/consolidation (vs. today's skill-driven
  "a skill decides what's worth saving") — also not v1. **Trigger to
  revisit:** a single workspace's notes genuinely stop fitting in context,
  or users actually want search across months of accumulated history
  rather than "what does this workspace currently know" — a real signal,
  not a timeline.
- Any UI language other than English.
- A mobile app.

**Permanently out of scope, not a phasing question:**
- Trade or order execution, in any form. This is a research tool, not a
  trading terminal — see the guardrail in §5.
- Personalized investment advice. Minty narrates data and analysis; it
  never tells the user what to buy or sell.
- Live-generated, auto-saved skills. Skills are curated and hand-authored,
  reviewed like any other code change — never generated by the model at
  runtime and kept for reuse. (The old repo's own restraint here — one
  fixed skill library across many iterations — is worth keeping, not
  reopening.)
- A hosted/cloud version. Local-first, on the user's own machine, always —
  this is the core of the pitch in §1, not a v1-only constraint.

## 4. Architecture (one page)

Decided so far:

- **Skills: one directory per skill** (`SKILL.md` + `scripts/`), per the
  Agent Skills spec. Not a style choice — this is how skill discovery
  actually works, and it's a clean contribution boundary for Track 2 (a
  skill PR touches exactly one folder).
- **Corrected during the skill-porting pass (previously wrong in this
  doc): the canonical location is `.claude/skills/<name>/`, not a
  top-level `skills/<name>/`.** This section originally claimed Track 1's
  engine "owns skill loading itself and isn't bound to Claude Code's
  discovery mechanism," so it could read a plain top-level `skills/`
  directly — a reasonable-sounding narrative that turned out to be false
  at the plumbing level, not just unverified. Live-tested by dumping a
  connected session's own `SystemMessage.data["skills"]`: with skill
  packages under top-level `skills/`, the model saw an unrelated set of
  host/CLI-bundled skills and *none* of this project's own, despite
  `ToolConfig.skills` correctly listing them; moving the exact same
  packages to `.claude/skills/` made them appear immediately.
  `setting_sources=["project"]` + `skills=[...]` *is* Claude Code's own
  project-skill discovery — the Agent SDK's transport shells out to the
  `claude` CLI (see §8), so this mechanism was never actually
  Minty-controlled, regardless of which process owns the surrounding
  conversation loop. One canonical copy either way (not the old repo's
  canonical-plus-generated-view split, and no `tools/generate_skill_views.py`
  equivalent) — it just lives at the path the mechanism actually reads, not
  the path a clean-sounding narrative assumed it would. Revisit only if a
  second harness with genuinely different discovery needs gets built.
- **No formal skill versioning.** Git history is the version history for a
  skill's content — a SKILL.md changing between commits is a normal code
  change, reviewed the normal way. A SemVer-per-skill scheme would only
  earn its keep if something concrete needed it (pinning behavior for
  reproducibility, running multiple versions concurrently) — neither
  applies yet. Keep plain frontmatter per skill (name, one-line trigger
  description, attribution if adapted) as ordinary metadata, not
  versioning.

**Layer 1 — Kite MCP, via `kite_gateway`.** Zerodha's own hosted MCP server
(`mcp.kite.trade`). Minty never talks to it directly — everything routes
through `kite_gateway`, a thin proxy that only ever registers a read-only
subset of Kite's real tool list (holdings, positions, quotes, historical
data, margins, orders-read) and never the six order-placing/-modifying
tools — by omission from the tool surface, not by a permission check
someone could get wrong. The resulting session persists locally between
runs (git-ignored, owner-only file permissions, time-limited).

**Layer 2 — Minty-owned data servers.** Four local MCP servers Minty
writes and owns: `india_price` (quotes/OHLCV/fundamentals), `india_filings`
(announcements, shareholding pattern, FII/DII flows, surveillance lists),
`india_macro` (policy rates, exchange calendar), `india_news` (headlines).
Broker-agnostic by convention — symbols/sectors as plain arguments, never
a Kite-specific response shape — so a second broker later touches Layer 1
only.

**Engine.** Minty's own process, not Claude Code. A thin `Harness`
protocol is the one seam to a model backend; `ClaudeAgentSDKHarness` is
the sole implementation for v1, calling Claude directly via the Agent SDK
rather than shelling out to an interactive `claude` CLI session. The
engine owns dispatch, guardrail enforcement (denying the six order tools a
second time, independent of Layer 1's omission — defense in depth), skill
loading (`.claude/skills/<name>/SKILL.md` — see above for why it's not a
plain top-level `skills/`), and, unlike the old repo, real multi-turn
session state — the one thing that makes this a standalone tool rather
than a single-shot script.

**Workspace file layout.** A local directory, never committed:
root-level `notes.md` / `preferences.md` / `portfolio.md` for durable
cross-cutting facts, `workspaces/<name>/notes.md` for topic/thesis-scoped
findings. Plain markdown, the same compounding-vault model as the old
repo — this part worked and isn't being redesigned, just carried over.

## 5. Non-negotiables

Rules about how anything in scope must behave — not subject to
re-litigation per feature, only revisited as a deliberate, separately
scoped decision:

- **No order execution, structurally.** The six order-placing/-modifying
  Kite tools are never registered in any tool surface the model sees —
  absent, not merely denied. Enforced at more than one layer (gateway +
  engine dispatch) so it doesn't depend on any single mechanism holding.
- **Deterministic calculation only.** Money figures (returns, P&L,
  allocation %, ratios) are always computed in code, never by LLM
  arithmetic. The model narrates numbers that already exist; it doesn't
  produce them.
- **Grounding.** Every numeric claim traces to a real tool result or a
  computed file, never model memory. Every output ends with a Sources
  footer (tool/source + as-of date).
- **SEBI disclaimer.** Attached automatically to any output that could be
  read as investment advice.
- **User data stays local.** Notes, preferences, portfolio holdings,
  workspace content — never committed to the repo, never assumed by code
  that ships.
- **Be polite to data sources.** All exchange (NSE/BSE) fetching goes
  through cached, rate-limited fetchers with backoff — never hot-loop a
  real exchange endpoint from a session.

## 6. What Carries Over vs. Rebuilt Clean

**Carries over as-is (tested, working):**
- Layer 2 MCP servers: `india_price`, `india_filings`, `india_macro`,
  `india_news`
- `kite_gateway` guardrail (allow-list design, session persistence)
- Skill *content* (ported into the new single-source folder convention)

**Rebuilt clean:**
- The engine — interactive multi-turn sessions, the Harness swap point
  (the old engine was single-shot only and never reached this)
- Skill loading — single canonical source, no generated view (see
  Architecture)

**Dropped entirely:**
- `tools/generate_skill_views.py` and the generated-view mechanism
- `refresh-holdings` skill
- The unattended `launchd` digest pipeline (replaced by manual-trigger +
  reminder)

## 7. Success Criteria

**Track 1 — standalone product:**
- A real multi-turn conversation works end to end through Minty's own
  entrypoint, with no Claude Code interface involved at any point.
- Compounding is proven again under the new engine: a genuinely separate
  session picks up an open thread from a prior session's notes without
  the user re-explaining context — the same bar the old repo proved once
  and the one thing that must survive the rebuild.
- The reminder-then-manual-trigger digest flow (§2) works reliably across
  N consecutive on-demand invocations with no code fix required in
  between — reliability measured per-invocation, not per-unattended-day,
  since nothing runs unattended anymore.
- All three v1 must-have skills (`docs/skills.md`) run successfully
  against a real connected Zerodha account, with grounded output and a
  Sources footer on each.

**Track 2 — contributor surface:**
- A person who isn't the owner can clone the repo, follow Getting
  Started, and get a working session with no undocumented steps.
- At least one real skill contribution (even a small one) goes through
  the documented PR process — template followed, CI green — without
  hand-holding beyond normal code review.

Both tracks should hold before this repo is treated as ready to widen
access beyond the owner — the same lesson from the old repo's launch
discussion: "ready to announce" and "ready to redact" turned out to be
different bars, and this list is what closes that gap for v2 up front
instead of finding it after the fact.

## 8. First-Run Experience & Connecting Accounts

Two separate connections happen at onboarding, and they're handled very
differently on purpose:

**1. LLM backend (Claude) — checked, not automated.** On first run, Minty
checks whether the machine already has a working Claude subscription login
(the same one the Agent SDK reuses under the hood). If not, Minty tells
the user to run their own login and waits — it does not attempt to drive
that login flow itself. Authenticating a subscription is exactly the kind
of action a tool shouldn't perform on a user's behalf.

**2. Zerodha account — OAuth in the user's own browser, never through
Minty.** On first use of any Kite-touching capability, Minty calls the
Kite gateway's `login` tool, which returns a one-time clickable OAuth URL.
Minty surfaces that URL; the user completes Zerodha login (and any 2FA)
entirely in their own browser. Credentials never pass through Minty or the
model at any point — by construction of the OAuth redirect, not by a
promise about how the model will behave. Once done, the gateway persists
the resulting session locally (git-ignored, owner-only permissions,
time-limited), so subsequent runs don't require re-login until it expires
— at which point Minty detects the failure and prompts the same flow
again. No separate "refresh" step or skill needed for this (this is what
made the old repo's `refresh-holdings` skill unnecessary — see §2/§3).

**After that, it's just conversation.** The user asks for a digest, a
health check, a red-flag scan on a name; Minty pulls real holdings,
prices, filings, and news through Layer 1/2 automatically and answers
grounded in that data.

**One thing worth stating up front in the onboarding text itself, not just
in a docs file:** exactly what Minty can and cannot do with the connected
account — read-only, structurally, regardless of what the underlying
Zerodha OAuth grant technically permits. A stranger connecting a real
brokerage account should see that claim at the moment they're asked to
connect it, not have to go find it in `docs/vision.md` §5.

---

See `docs/skills.md` for the per-skill spec template and detail.
