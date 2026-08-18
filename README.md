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
git clone https://github.com/EternalTuring/minty-core.git minty
cd minty
uv sync
uv run python ingest/build_instruments_master.py
uv tool install --editable .
```

- `uv sync` installs every Python dependency (and Python itself, if
  needed) into a project-local `.venv` — nothing system-wide.
- `uv run python ingest/build_instruments_master.py` builds a local
  reference database (`data/instruments.db`) of NSE/BSE symbols and sector
  classifications — a few seconds, no login or API key needed (two public,
  no-auth sources). Without it, morning-digest's sector-materiality check
  silently degrades instead of failing loudly, so it's easy to miss if
  skipped.
- `uv tool install --editable .` registers a global `minty` command, so
  from here on you just type `minty` — the same way you'd type `claude`
  — instead of `uv run python -m engine.interactive`. See "How the
  `minty` command finds your data" below for what "install" actually
  means here.

## How the `minty` command finds your data

`uv tool install --editable .` doesn't copy Minty anywhere — it's an
*editable* install, so the global `minty` command is really just a
pointer back at the exact repo you ran that command from. Run `minty`
from `/tmp`, your Desktop, wherever: it still reads/writes *this* repo's
`workspaces/`, `.mcp.json`, and `.claude/skills/`. Verified live, including
running it from a directory with no relation to the repo at all.

**One install = one vault.** There's no per-directory project discovery
here the way `claude` itself has — `minty` always points at whichever
repo clone it was last installed from. Two consequences worth knowing:

- Different people/machines: no conflict — each person's own
  `uv tool install --editable .` (from their own clone) is independent.
- **Same machine, a second clone:** installing again repoints `minty` at
  the new clone instead of the old one (`uv tool install` uninstalls the
  old mapping and installs the new one) — verified live. The old clone's
  files aren't touched or deleted, but `minty` stops seeing them. If you
  ever clone Minty a second time on the same machine, know that
  reinstalling from it silently switches which repo `minty` operates on.

## Onboarding

Three steps, in order, from a fresh install to your first real result.

1. **Confirm Claude is connected.**
   ```bash
   minty
   ```
   Minty checks your Claude login itself before printing anything else.
   Already logged in (the common case)? You'll see `Minty — connected.`
   immediately. Not logged in? Minty runs `claude auth login` for you and
   waits — you still complete the real sign-in in your own browser, this
   just saves you the extra step of running it yourself, and there's no
   lingering `claude` chat session to get stuck in afterwards. If login
   still doesn't take, Minty exits with `Couldn't sign in to Claude — run
   'claude auth login' and try again.` — run that yourself, then rerun
   `minty`.

2. **Connect Kite.** Set a workspace, then ask for your holdings:
   ```
   you> /workspace daily
   you> what are my holdings
   ```
   Minty replies with a one-time Kite login link. Click it, log in in
   your own browser (Minty never sees your Zerodha credentials), then
   tell Minty you're done — it picks up from there. Verified end to end,
   including from a genuinely fresh clone with no prior session.
   `/workspace daily` only needs to be set once per session — creates
   `workspaces/daily/` automatically, and everything you do lands there
   for next time.

3. **Run your first skill.**
   ```
   you> give me the morning digest
   ```
   or `how's my portfolio doing` / `any red flags on RELIANCE`. That's
   the whole loop from here — ask in plain language, get back a grounded,
   sourced answer.

## Available skills

- **morning-digest** — "give me the morning digest," "what happened
  overnight" — a short, portfolio-aware daily brief.
- **portfolio-health-check** — "how's my portfolio doing," "am I too
  concentrated in anything" — total P&L, concentration, winners/losers.
- **red-flag-scan** — "any red flags on RELIANCE" — governance/safety
  checklist on one held or watchlist name.

Every output is grounded in real tool calls (never model memory), ends
with a Sources footer, and carries the SEBI disclaimer. Minty is
read-only against your broker by construction — order-placing tools are
never in its tool surface at all, not just withheld by policy.

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
uv run python -m engine.run --workspace daily "<prompt>"
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
- No CI, no CONTRIBUTING doc yet — contributor-facing surface
  (`docs/vision.md` §7 Track 2) hasn't started.
