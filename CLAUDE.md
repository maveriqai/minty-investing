# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What This Is

Minty Investing (MaverIQ AI) — local-first research and portfolio-monitoring
tool for Indian retail equity investors, built against a real connected
Zerodha account. Not a hosted web app: a `workspace/` directory on disk that
compounds findings across sessions, the Obsidian-for-investing framing.

**Read `docs/vision.md` first** — problem/audience, architecture, non-
negotiables, and success criteria. `docs/skills.md` is the per-skill spec
companion. Both are living docs updated as decisions get made; this file
should agree with them — if it drifts, fix both.

This repo (`minty-investing`, pushed to `github.com/maveriqai/minty-investing`,
private) is the active build. It supersedes an earlier, separate `Minty`
repo — Layer 2 MCP servers and skill *content* carried over from there
(ported, not copied blindly), but the engine, skill-loading mechanism, and
workspace model were rebuilt clean here. Don't assume the old repo's file
paths or conventions (`workspaces/<name>/`, `tools/generate_skill_views.py`,
a canonical `skills/<name>/SKILL.md`) apply — see "What Carries Over vs.
Rebuilt Clean" in `docs/vision.md` §6.

## Architecture

**Engine — Minty owns the agent loop.** `engine/` is a real Python package
(not Claude Code), calling Claude directly via the Agent SDK
(`ClaudeAgentSDKHarness`). It owns dispatch, guardrail enforcement, skill
loading, tool-call budgeting/capture, the Sources footer, and real
multi-turn session state. `minty` (the installed CLI entry point,
`engine.interactive:main`) is the one true way to run this — not "open
Claude Code in this repo."

**Layer 1 — Kite MCP, via `mcp/kite_gateway/`.** Minty never talks to
`mcp.kite.trade` directly. The gateway is a thin proxy that only ever
registers a read-only subset of Kite's real tools (holdings, positions,
quotes, historical data, margins, orders-read) — the six order-placing/
-modifying tools (`place_order`, `modify_order`, `cancel_order`,
`place_gtt_order`, `modify_gtt_order`, `delete_gtt_order`) are never in the
tool surface at all, by omission, not a permission check that could be
gotten wrong. Session persistence is local, git-ignored, owner-only file
permissions, time-limited.

**Layer 2 — Minty-owned data servers**, one directory per server under
`mcp/`, single-file `server.py` using `FastMCP`, tools registered
explicitly at the bottom: `india_price` (quotes/OHLCV/fundamentals via
yfinance), `india_filings` (announcements, shareholding, FII/DII, NSE
surveillance, and — since issue #25 — fetching/extracting an actual filed
document's text, the governed replacement for the raw Bash+curl the model
was reaching for), `india_macro` (policy rates, exchange calendar),
`india_news` (headlines), `india_screener` (Screener.in-scraped ROE/ROCE —
fills a real yfinance gap, see `docs/screener-integration-design.md`).
Broker-agnostic by convention — symbols/sectors as plain arguments, never a
Kite-specific shape. Shared fetch/cache/rate-limit code lives in
`mcp/common/`, never duplicated per server (e.g. `nse_fetch.py`,
`screener_fetch.py` + `screener_parse.py` fetch/parse split, `instruments.py`).
Every tool returns a `{"source", "as_of", "data"}` envelope.

**Skills — single canonical source, no generated view.** `.claude/skills/
<name>/SKILL.md` + `scripts/` is the only copy — this is a corrected-in-
place decision (`docs/vision.md` §4): a top-level `skills/<name>/` was
tried first on the theory that the engine could read it directly, but
Claude Agent SDK's `setting_sources=["project"]` skill discovery only ever
reads `.claude/skills/`, live-verified by dumping `SystemMessage.data["skills"]`.
The top-level `skills/` directory that still exists holds only
`README.md` and `THIRD-PARTY-NOTICES.md` (contributor-facing docs and
attribution), not skill sources. There is no `tools/generate_skill_views.py`
equivalent here — edit `.claude/skills/<name>/SKILL.md` directly.

**Staged skills — opt-in, for unbounded single-turn context.** A skill can
declare a `stages` frontmatter block (`docs/staged-skill-execution-design.md`);
the engine (`engine/staged_skills.py`, `engine/staged_skill_tools.py`)
splits it into several fresh sessions instead of one growing turn, exposed
as its own `run_staged_<skill>` tool. Built after a real bug: a 98-holding
`morning-digest` run silently dropped citations from its own Sources footer
in one ~31-minute, ~70-tool-call turn. Most skills don't need this — only
declare it when call volume scales with the user's own data (portfolio
size, holding count).

**Deterministic scripts, not LLM arithmetic.** Skills call typed
`run_<script>` SDK tools (`engine/skill_tools.py`) that shell out to
`.claude/skills/<name>/scripts/*.py` for ranking/flagging/math (e.g.
`screen_rank.py`, `red_flag_check.py`, `digest_math.py`) — never raw Bash,
never model-computed money figures. `engine/tool_capture.py`'s
`CAPTURE_SPECS` auto-saves raw MCP tool results to `workspace/data/` under
fixed, skill-documented filenames, keyed by `(mcp_server, tool_name)`.
`engine/tool_budget.py` audits (doesn't enforce) a skill's own
`tool_call_budgets` frontmatter, printed as an engine diagnostic when a
turn goes over.

**Workspace — one fixed, unnamed `workspace/` per install.** Not
per-topic, not named — a real single directory (`docs/next-phase-plan.md`
§4, decided after live dogfooding showed naming was unused friction).
`workspace/notes.md` holds durable findings + a `## Preferences` section;
`workspace/theses/<SYMBOL>.md` is the one per-symbol exception
(thesis-tracker reads/merges/rewrites it), and
`workspace/research/sectors|stocks|themes/<key>.md` (added with
research-discovery, `docs/research-discovery-plan.md`) is the same kind
of read-merge-rewrite exception, keyed by subject instead of symbol.
Everything else (`morning-digest`, `portfolio-health-check`,
`red-flag-scan`, `screen-indian-stocks`) writes independent, date-stamped
files into `workspace/results/`, never edited after the fact — raw tool
captures go to
`workspace/data/`, auto-captured verbatim by the engine
(`engine/tool_capture.py`) and never hand-authored or patched by the model
via `Write` — a failed, corrupted, or oversized capture is reported as a
gap, the same honest-gap policy every skill already applies to a missing
input, not reconstructed from partial reads (issue #24).
`workspace/sessions/<timestamp>.md` (issue #13,
`engine/session_transcript.py`) holds one raw transcript per REPL run,
engine-appended every turn. `workspace/memory_candidates.md` (issue #14,
`engine/memory_candidates.py`) is the append-then-clear staging file for
memory-candidate review — see "Model-initiated writes" below. The Zerodha
account identity anchor lives outside the workspace, at install-wide
`data/account_identity.json` — written once, deterministically, on the
first successful `kite_gateway.get_profile` call, never overwritten by a
model-initiated tool call. `MINTY_WORKSPACE` can resolve a named
`.dev-workspaces/<name>/` sandbox for test isolation only — never a
conversational command, never something a real install needs.

**Model-initiated writes — explicit remember + staged candidates (issue
#14).** Two mechanisms let the model write to the workspace on its own
initiative, outside any skill's deterministic-script path: (1) when the
user explicitly asks Minty to remember/note/save something, an always-on
system-prompt instruction (`_REMEMBER_SYSTEM_PROMPT`,
`engine/harnesses/claude_agent_sdk.py`) has the model call
`update_workspace_notes` directly, in the same turn; (2) when something
durable surfaces without an explicit ask, `stage_memory_candidate`
(`engine/memory_candidates.py`) lets the model queue it to
`workspace/memory_candidates.md` — never `notes.md` directly. Nothing
staged this way reaches `notes.md` without a human confirming it: at the
next REPL start, `engine/interactive.py`'s `_repl` reads and clears any
pending candidates and runs a review turn presenting them for confirm/
discard before any `update_workspace_notes` call. This pipeline is
prompt-engineered end to end, not code-enforced the way order-execution
denial is — see issue #23 for the deferred architectural follow-up.

## Non-Negotiable Product Rules

(`docs/vision.md` §5 is the source of truth — summarized here for quick
reference.)

- **No order execution, structurally — not just by policy.** The six
  order-placing/-modifying Kite tools are never registered in any tool
  surface the model sees, enforced at more than one layer — the gateway
  never puts them in `ALLOWED_TOOLS` (`mcp/kite_gateway/server.py`), and a
  harness-agnostic `GuardrailPolicy` (`engine/guardrail.py`, consumed by
  `engine/harnesses/claude_agent_sdk.py`) denies the same six names a
  second time, independent of the gateway — so it doesn't depend on any
  single mechanism holding. Never call them from any skill, script, or
  session.
- **Deterministic calculation only.** Money figures (returns, P&L,
  allocation %, ratios) are always computed in code (a `run_<script>`
  tool), never by LLM reasoning. The model narrates numbers that already
  exist.
- **Grounding.** Every numeric claim traces to a real tool result or a
  computed file, never model memory. The engine itself appends the Sources
  footer (`engine/sources_footer.py`, built from what actually got captured
  to `workspace/data/` that turn) — don't rely on the model to remember to
  write one.
- **SEBI disclaimer**, attached automatically by the same engine step as
  the Sources footer to any output that could be read as investment advice:

  > Minty is a research tool, not investment advice. This is educational
  > analysis of publicly available data. Consult a SEBI-registered
  > investment adviser before acting.
- **User data stays local and git-ignored** — `workspace/`,
  `.dev-workspaces/`, `results/`, `data/`, root `notes.md`. Never commit
  them, never assume their contents in code that ships.
- **Skills are curated and hand-authored** — reviewed like any other code
  change, never generated by the model at runtime and kept for reuse.
- **Be polite to data sources.** All NSE/BSE fetching goes through cached,
  rate-limited fetchers with backoff (`mcp/common/`). Screener.in has no
  official API or rate-limit contract — treat it more cautiously than a
  documented endpoint (5s/request throttle, byte-exact cache, circuit
  breaker — see `mcp/common/screener_fetch.py` and the README's "Data
  sources" section). Never hot-loop any exchange or scraped endpoint from a
  session.

## India Market Conventions

- Market hours: NSE/BSE equities 09:15–15:30 IST, Mon–Fri, exchange-holiday
  aware.
- Symbols: NSE primary (`RELIANCE`, yfinance `RELIANCE.NS`); BSE `.BO` only
  when asked. Indices: NIFTY 50, SENSEX, BANKNIFTY, INDIA VIX.
- Money: ₹ with crore/lakh units (₹1,234 cr, not ₹12.34B). Percentages to
  2dp.
- Fiscal year: April–March. "Q3 FY26" = Oct–Dec 2025. Never use calendar
  quarters for results.
- Accounting: Ind AS terminology (not US GAAP). Consolidated numbers by
  default; flag when using standalone (`india_screener.get_fundamentals`'s
  `consolidation` field makes this explicit).
- Valuation: risk-free rate = 10Y G-Sec yield; India equity risk premium —
  never US treasury rates.
- Settlement T+1; F&O monthly expiry last Thursday (weekly for indices).
- Where two sources give genuinely different numbers for the same
  fundamental (e.g. `india_price`'s `return_on_equity_pct` vs.
  `india_screener`'s `roe_pct` — up to 5.4pp apart on the same company by
  methodology, see `docs/screener-integration-design.md` §2), never present
  one as the universal figure — say which source it's from.

## Conventions

- **Python 3.12+, `uv`** for everything (`uv sync`, `uv run`). `ruff` for
  lint (`uv run ruff check .`), `pytest` for tests (`uv run pytest`,
  `tests/`). Network-gated live tests are marked `@pytest.mark.network` and
  skipped by default (`addopts = "-m 'not network'"` in `pyproject.toml`) —
  run deliberately with `-m network` when live-verifying against a real
  external call.
- **Only `engine/` is an importable package** (`pyproject.toml`'s
  `[tool.hatch.build.targets.wheel]`). `mcp/`, `ingest/`, `skills/` are
  invoked as scripts or read as data via repo-relative paths, never
  imported as a package — tests load `mcp/<name>/server.py` and
  `.claude/skills/<name>/scripts/*.py` via
  `importlib.util.spec_from_file_location` under a unique module name to
  avoid collisions between sibling `server.py`/script files (see any
  `tests/test_india_*.py` or `tests/test_screen_rank.py` for the pattern).
- **MCP servers**: one directory per server under `mcp/`, single-file
  `server.py` using `FastMCP`, tools registered explicitly at the bottom so
  functions stay importable in tests. Docstrings are the tool contract —
  write them for the model: when to use the tool, the return shape, and any
  caveat about the underlying source's reliability. Shared fetch/cache/
  rate-limit code goes in `mcp/common/`, never duplicated per server.
- **Skills**: `.claude/skills/<name>/SKILL.md` (Agent Skills spec
  frontmatter — `name`, `description` as the trigger, optional
  `expected_outputs`, `tool_call_budgets`, `deterministic_scripts`,
  `stages`) + `scripts/`. Edited directly — no build step. Top-level
  `skills/README.md` and `skills/THIRD-PARTY-NOTICES.md` are contributor
  docs and attribution, not sources.
- **Layout**: `engine/` the real package (agent loop, harness, guardrail,
  skill loading, tool budgeting/capture, Sources footer, reminder CLI) ·
  `mcp/` Layer 1/2 servers · `ingest/` local reference-data builders (e.g.
  `build_instruments_master.py`) · `.claude/skills/` canonical skill source
  · `skills/` top-level contributor docs only · `workspace/` the one fixed
  install-wide workspace, git-ignored (`data/`, `results/`) ·
  `data/account_identity.json` the install-wide Kite identity anchor,
  git-ignored · `tests/` mirrors the above, one `test_*.py` per module ·
  `docs/` product/design docs (`vision.md`, `skills.md`,
  `screener-integration-design.md`, `staged-skill-execution-design.md`,
  `next-phase-plan.md`, `investing-workflow-roadmap.md`).

## Open Items

See `docs/next-phase-plan.md` §8 and the README's "Known gaps" section for
what's genuinely unresolved (Windows support — `os.fchmod` blocker in
`kite_gateway`'s session persistence, untested reminder backend; no CI
yet (`CONTRIBUTING.md` now covers conventions, but nothing enforces them
automatically); issue #23 — the memory-extraction staging pipeline's
confirm-before-write guarantee is prompt-only, not code-enforced). When a
task seems to depend on one of these, stop and check rather than assuming
it's already solid.
