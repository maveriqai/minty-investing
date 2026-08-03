# Minty v2 — Skill Specs

Companion to `vision.md`. One consistent template per skill, kept separate
from the vision doc so it stays scannable as skills are added later.

## Template

- **Name & trigger** — one line on when someone reaches for this vs.
  another skill (avoids ambiguity that would otherwise need a paragraph to
  resolve later)
- **Input** — which Layer 1/2 tools it calls, and what the user supplies
  (symbol, sector, etc.)
- **Output shape** — what it actually produces (a brief, a table, a flag
  list)
- **Grounding rule** — what must be computed in code vs. narrated by the
  model, specific to this skill
- **v1 priority** — must-have / later

## v1 Must-Haves

| Skill | Trigger | Input | Output | Notes |
|---|---|---|---|---|
| morning-digest | Daily portfolio/market snapshot | Holdings + index quotes + FII/DII flow + surveillance | Short markdown brief | Generated on-demand only (see vision.md §2) — reminder notifies, this generates |
| portfolio-health-check | Portfolio-wide concentration/winners-losers | Full holdings | Structured review | |
| red-flag-scan | Governance check on one held/watchlist name | One symbol | Flag list w/ severity | |

## Later

| Skill | Trigger | Input | Output | Notes |
|---|---|---|---|---|
| screen-indian-stocks | Candidate ideas from a sector/theme | Sector/theme | Ranked candidate list | Needs broader sector coverage than currently available |
| thesis-tracker | Define/update/review a thesis on one name | Symbol + user-stated thesis | Thesis diff over time | Needs multiple digest cycles to be useful |

## Dropped

- **refresh-holdings** — superseded by the manual-trigger decision in
  `vision.md` §2; an interactive session can always complete Kite's login
  itself, so there's no headless-OAuth gap left to work around.
