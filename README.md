# Minty

Local-first research and portfolio-monitoring tool for Indian retail equity
investors (MaverIQ AI). Not a hosted web app — a real directory on disk that
holds its own findings, notes, and digests, and compounds over time as you
use it. See [`docs/vision.md`](docs/vision.md) for the full scope and
[`docs/skills.md`](docs/skills.md) for what each skill does.

**Status:** this file describes the intended install/first-run experience
for review. Everything below is built and live-verified, including a full
fresh-clone-to-first-digest run — see "Known gaps" at the end for the
remaining rough edges (none block a normal first run).

## Prerequisites

New to any of these? Install in this order — each step includes a command
to confirm it worked before moving to the next.

1. **Claude Code CLI** (`claude`) — Minty reuses this login, it doesn't
   have its own. Requires a Claude Pro/Max/Team/Enterprise/Console
   account (the free claude.ai plan doesn't include Claude Code access).

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash   # macOS/Linux/WSL
   ```
   ```powershell
   irm https://claude.ai/install.ps1 | iex           # Windows PowerShell
   ```
   Then log in and confirm it worked:
   ```bash
   claude            # opens a session — follow the browser login prompt, then exit
   claude --version  # should print a version number, not an error
   ```

2. **`uv`** — installs and runs Python projects; also manages Python
   itself, so you do **not** need to install Python separately (`uv
   sync` below will fetch a matching Python 3.12+ automatically if your
   system doesn't already have one).

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux
   ```
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
   ```
   Confirm:
   ```bash
   uv --version
   ```

3. **Git** — already on most macOS/Linux machines; confirm with
   `git --version`. If that fails: `brew install git` (macOS) or
   [git-scm.com/downloads](https://git-scm.com/downloads)
   (Windows/Linux).

4. **A Zerodha/Kite account** — nothing to install now. You'll connect
   it conversationally in Onboarding step 2, below — no API key to
   generate in advance.

Nothing else to configure — no `.env` file, no API keys to set for Minty
itself.

## Quickstart

```bash
git clone https://github.com/maveriqai/minty-investing.git minty
cd minty
uv sync
uv run python ingest/build_instruments_master.py
uv run python scripts/install_entrypoint.py
```

- `uv sync` installs every Python dependency (and Python itself, if
  needed) into a project-local `.venv` — nothing system-wide.
- `uv run python ingest/build_instruments_master.py` builds a local
  reference database (`data/instruments.db`) of NSE/BSE symbols and sector
  classifications — a few seconds, no login or API key needed (two public,
  no-auth sources). Without it, morning-digest's sector-materiality check
  silently degrades instead of failing loudly, so it's easy to miss if
  skipped.
- `uv run python scripts/install_entrypoint.py` registers a global `minty`
  command (equivalent to `uv tool install --editable .`, which it runs for
  you), so from here on you just type `minty` — the same way you'd type
  `claude` — instead of `uv run python -m engine.interactive`. See "How
  the `minty` command finds your data" below for what "install" actually
  means here, and why this script — not the raw `uv tool install` command
  — is the way to run it.

## How the `minty` command finds your data

`uv tool install --editable .` doesn't copy Minty anywhere — it's an
*editable* install, so the global `minty` command is really just a
pointer back at the exact repo you ran that command from. Run `minty`
from `/tmp`, your Desktop, wherever: it still reads/writes *this* repo's
`workspace/`, `.mcp.json`, and `.claude/skills/`. Verified live, including
running it from a directory with no relation to the repo at all.

**One install = one vault.** There's no per-directory project discovery
here the way `claude` itself has — `minty` always points at whichever
repo clone it was last installed from. Two consequences worth knowing:

- Different people/machines: no conflict — each person's own
  `uv tool install --editable .` (from their own clone) is independent.
- **Same machine, a second clone:** installing again repoints `minty` at
  the new clone instead of the old one (`uv tool install` uninstalls the
  old mapping and installs the new one) — verified live. The old clone's
  files aren't touched or deleted, but `minty` stops seeing them.
  `scripts/install_entrypoint.py` (the Quickstart's install step) is the
  concrete mitigation: it detects when an install would repoint `minty`
  away from a different repo and asks for confirmation first, instead of
  silently switching. Scripting a fresh install non-interactively (CI, a
  provisioning script)? Pass `--yes` to skip the prompt.

**Check which repo `minty` currently points at**, e.g. if you have more
than one clone (a dev checkout and a fresh-install test, say) and aren't
sure which one a plain `minty` in a random terminal will actually read
from:

```bash
uv run python scripts/install_entrypoint.py --where
```

Prints the absolute path of the repo the global `minty` command is
currently wired to — the same check `install_entrypoint.py` runs
internally before deciding whether to prompt you about repointing it.

## Onboarding

Three steps, in order, from a fresh install to your first real result.

1. **Confirm Claude is connected.**
   ```bash
   minty
   ```
   Run this from wherever you like — the repo folder Quickstart just left
   you in, or any other directory on your machine. Location genuinely
   doesn't matter (see "How the `minty` command finds your data" above).

   Minty checks your Claude login itself before printing anything else.
   Already logged in (the common case)? You'll see `Claude account
   already connected.` followed by `Minty — connected.` Not logged in?
   Minty runs `claude auth login` for you and waits — you still complete
   the real sign-in in your own browser, this just saves you the extra
   step of running it yourself, and there's no lingering `claude` chat
   session to get stuck in afterwards. If login still doesn't take,
   Minty exits with `Couldn't sign in to Claude — run 'claude auth
   login' and try again.` — run that yourself, then rerun `minty`.

2. **Connect your Zerodha account.** Minty checks this automatically too,
   the moment it starts — right after the Claude confirmation you'll see
   one of two lines:
   ```
   Holdings for account AB1234 found — last refreshed 2 days ago.
   ```
   (already connected — nothing to do), or:
   ```
   Zerodha not connected yet — ask something like "what are my holdings"
   anytime to connect, or skip for now and you'll be prompted when you
   need it.
   ```
   If you see the second line, connect the same way Claude's login in
   step 1 worked — ask for anything that needs live account data and
   Minty prompts you:
   ```
   you> what are my holdings
   ```
   Minty replies with a one-time Kite login link. Click it, log in in
   your own browser (Minty never sees your Zerodha credentials), then
   tell Minty you're done — it picks up from there. Once connected, this
   persists across sessions until Kite's own daily re-login requirement
   kicks in — you won't repeat this every conversation.

3. **Run your first skill.**
   ```
   you> give me the morning digest
   ```
   or `how's my portfolio doing` / `any red flags on RELIANCE`. That's
   the whole loop from here — ask in plain language, get back a grounded,
   sourced answer. Everything you do compounds automatically from here —
   what Minty finds, and anything durable you tell it, carries into your
   next conversation with no setup on your part. It all stays on your
   machine, in this repo, never uploaded anywhere.

## Available skills

- **morning-digest** — "give me the morning digest," "what happened
  overnight" — a short, portfolio-aware daily brief.
- **portfolio-health-check** — "how's my portfolio doing," "am I too
  concentrated in anything" — total P&L, concentration, winners/losers.
- **red-flag-scan** — "any red flags on RELIANCE" — governance/safety
  checklist on one held or watchlist name. Checks
  `workspace/research/stocks/<SYMBOL>.md` for a prior check on the name
  first, and merges its own findings back into that same file.
- **thesis-tracker** — "track a thesis on RELIANCE," "is my thesis on X
  still intact" — pillars, risks, catalysts, and conviction for one held
  or watchlist name, tracked as a living scorecard across sessions. A
  brand-new thesis picks up and cites any prior research note on that
  symbol, and writes one line back once the thesis opens.
- **screen-indian-stocks** — "find undervalued auto sector stocks,"
  "screen IT services for quality names" — sector/theme candidate
  discovery ranked on valuation/quality, Nifty 500 coverage only. Checks
  `workspace/research/sectors/<slug>.md` for prior context on the sector
  first, and merges its own screen history back into that same file.
- **research-discovery** — a headline, a tip, a vague hunch, or a
  cross-cutting question with no single sector/symbol yet ("what's
  driving FII outflows," "PLI scheme beneficiaries," "should I be
  worried about X given the rupee"). Asks one scoping question only if
  genuinely ambiguous, checks the workspace for prior research first,
  then runs a multi-angle pass and files the result to
  `workspace/research/sectors|stocks|themes/<key>.md` — the compounding
  front door for research that doesn't already know its own shape (see
  `docs/research-discovery-plan.md`).

All four of the above share those same `research/sectors|stocks|themes/`
bucket files — each skill owns its own section (`## Findings`, `## Screen
History`, `## Red-Flag Checks`) plus a shared `## Observations` log, so
research compounds no matter which skill you started from (see
`docs/research-notes-design.md`).

Every output is grounded in real tool calls (never model memory), ends
with a Sources footer, and carries the SEBI disclaimer. Minty is
read-only against your broker by construction — order-placing tools are
never in its tool surface at all, not just withheld by policy.

## Remembering things

Ask Minty to remember something explicitly, any time, whether or not a
skill is running:

```
you> remember that I don't want anything below ₹500cr market cap
```

It's saved to your workspace notes immediately — no confirmation step,
since you asked directly.

Minty also notices durable things you mention in passing — a preference,
an open thread — without you framing it as "remember this." Those aren't
written anywhere right away: they're queued, and at the start of your
*next* session Minty presents them for you to confirm or discard before
anything reaches your notes. Nothing lands in the hand-curated notes file
without you actually seeing it first.

## Finding what Minty has already written

Just ask — e.g. "what have you already researched about IT services?" or
"what do you have on RELIANCE?" Minty checks `research/`, `theses/`, and
your notes before answering, rather than answering from memory or saying
it doesn't know.

## Reporting a bug or a piece of feedback

Type `/feedback <what you want to report>` at any `you>` prompt:

```
you> /feedback the Kite login link wasn't clickable in my terminal
```

Your raw note is always saved locally to `workspace/feedback.md` first.
Minty then asks whether it can look at this session's own transcript and
tool-call log for supporting evidence — say yes, and it drafts a
ticket-shaped report (title + body, citing what actually happened, with
personal/financial detail redacted unless the bug is specifically about
it) and shows you the exact text before doing anything else with it.

Separately, Minty asks whether you'd like that report shared with the
Minty team as a real GitHub issue on
[maveriqai/minty-investing](https://github.com/maveriqai/minty-investing/issues).
Say yes and it files it via `gh issue create`, recording the issue URL in
`workspace/feedback.md`. If `gh` isn't installed or authenticated (or the
call fails for any other reason), you get the exact `gh issue create`
command to run yourself instead — nothing is lost either way. Decline the
evidence-gathering step, or decline sharing, and the note (or drafted
report) simply stays local in `workspace/feedback.md`.

## Data sources

Minty's own data tools (`mcp/india_price`, `india_filings`, `india_macro`,
`india_news`, `india_screener`) pull from a few different places, and
they're not all the same kind of source:

- **NSE/BSE via yfinance** (`india_price`) and **NSE's own public JSON
  API** (`india_filings`, `india_macro`) are polite wrappers around
  primary sources' own endpoints — throttled, cached, circuit-breaker'd
  (`mcp/common/`), same as any well-behaved client of a public API.
- **Screener.in** (`india_screener` — ROE, ROCE, and the multi-year ROE
  trend, which fills a real yfinance gap: it returns `null` ROE for entire
  sectors) is different in kind. Screener has no official API and no
  published rate-limit or markup-stability contract, so this is a plain,
  polite, anonymous scraper — 5s/request throttle, byte-exact cache,
  circuit breaker — not a wrapped endpoint. Anonymous access to the
  company pages this reads was verified live and works with no login; see
  [`docs/screener-integration-design.md`](docs/screener-integration-design.md)
  for the full investigation and the exact decisions behind it. Two things
  worth knowing if you're relying on this or adapting the skill elsewhere:
  - A field can genuinely be missing for a company (a young listing
    without 10 years of history) — that's reported as `None`, not an
    error. A field the parser *expected* but couldn't read, because
    Screener changed their page layout, is a different case: it's caught
    and surfaces as `data.error` rather than silently returning a wrong or
    misaligned number. If you ever see a Screener-sourced field come back
    wrong or missing, treat it as "their markup may have changed," not a
    bug in your query.
  - If Screener ever starts blocking anonymous requests — no rate-limit
    contract means this could change anytime — calls fail loudly with
    `ScreenerBlockedError`, mapped to `data.error`, not a hang or a
    quietly empty result. The fallback (session-cookie auth) is already
    designed, just not built, since it isn't needed today —
    `docs/screener-integration-design.md` §6 has the plan if you need to
    pick it up.

Every tool call is provenance-tagged (`source`, `as_of`), and every skill
output ends with a Sources footer, so any number Minty gives you traces
back to exactly where it came from and when it was fetched.

## Optional: morning reminder

Minty never runs unattended — every digest is generated on-demand, in a
real conversation you start (see `docs/vision.md` §2 for why). What *can*
run in the background is a lightweight, no-agent OS notification that
just nudges you each weekday morning to go ask for one:

```bash
uv run python -m engine.reminder.cli install                     # 08:30 Mon-Fri by default
uv run python -m engine.reminder.cli install --time 09:00 --message "Custom text"
uv run python -m engine.reminder.cli status
uv run python -m engine.reminder.cli uninstall
```

- **macOS** — installs a `launchd` LaunchAgent. Uses `terminal-notifier`
  if it's on `PATH` (`brew install terminal-notifier`) so clicking the
  notification opens a Terminal at the repo root; falls back to a plain
  `osascript` notification otherwise (works, but a long-documented macOS
  quirk means clicking it opens Script Editor instead of anything
  useful — `install` prints a note when this fallback is in effect).
- **Windows** — installs a Task Scheduler task that shows a native toast
  notification via PowerShell's built-in WinRT APIs, no `Install-Module`
  needed. Built and unit-tested, but **not live-verified** — see "Known
  gaps" below.
- Clicking the notification never runs anything on its own — starting the
  actual digest conversation stays a deliberate step you take, matching
  the "manual trigger, no agent involved" design in `docs/vision.md` §2.

## One-shot / scripted usage

For a single prompt with no ongoing conversation:

```
uv run python -m engine.run "<prompt>"
```

## Upgrading

Because the install is editable, most changes need nothing more than
pulling the latest code:

```bash
cd minty       # the repo `minty` is currently pointing at
git pull
uv sync        # picks up any new/changed dependencies — a no-op if none changed
```

New skills and code changes take effect on the next `minty` run — no
reinstall needed, since `minty` reads straight from these files. You'd
only rerun `uv tool install --editable .` if the command's own entry
point changes (rare) — not for routine updates.

## Known gaps

- **Windows is untested and has a known blocker.** The install steps
  above should work as written (`uv` and Claude Code both publish
  official Windows installers, and Minty's own path handling is all
  `pathlib`, not POSIX-specific) — but none of it has actually been run
  on Windows, only reasoned through by reading the code. One concrete,
  confirmed-by-reading blocker: `mcp/kite_gateway/server.py`'s session
  persistence calls `os.fchmod` to lock the saved Kite session id
  (a bearer credential) to owner-only — `os.fchmod` doesn't exist on
  Windows, so completing Kite login there will raise `AttributeError`
  instead of working. Needs a Windows-appropriate way to restrict that
  file before this is real Windows support, not just untested Windows
  support. The optional reminder CLI's Windows backend
  (`engine/reminder/windows.py`) is in the same boat — built and
  unit-tested against mocked `schtasks`/PowerShell calls, but never run
  for real, for the same no-Windows-machine reason.
- No CI yet — contributor-facing surface (`docs/vision.md` §7 Track 2)
  is still incomplete. `CONTRIBUTING.md` now covers the conventions side.
