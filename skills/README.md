# Skills

Curated, hand-authored workflows. **The actual skill packages (SKILL.md +
scripts/) live in `.claude/skills/<name>/`, not here** — corrected after
live-testing proved `setting_sources=["project"]`/`skills=[...]` is Claude
Code's own project-skill discovery, hardcoded to `.claude/skills/`
regardless of what owns the surrounding engine (see
`engine/config.py`'s `_minty_skill_names()` and `docs/vision.md` §4 for the
full correction — an earlier version of this doc and the vision doc
assumed otherwise). This `skills/` directory just holds project-level docs
about skills (this file, `THIRD-PARTY-NOTICES.md`) — no generated-view
machinery, one canonical copy, just not at this path.

**Ported from the original `Minty` repo, v1 must-haves (see
`docs/vision.md`/`docs/skills.md`):**
- `morning-digest/` — daily portfolio/market brief, on demand (see
  `docs/vision.md` §2 for why this isn't an unattended pipeline).
- `portfolio-health-check/` — portfolio-wide concentration/P&L/
  winners-losers.
- `red-flag-scan/` — governance/safety checklist on one held or watchlist
  stock.
- `thesis-tracker/` — define/update/review an investment thesis for a
  held or watchlist name, tracked per symbol in
  `workspace/theses/<SYMBOL>.md`.

**Not yet ported** (see `docs/skills.md`): `screen-indian-stocks` is
scoped "later," not dropped. `refresh-holdings` was dropped outright — it
existed to work around headless Kite OAuth in the old unattended
pipeline, which this project doesn't have (see `docs/vision.md` §2/§3).

See `THIRD-PARTY-NOTICES.md` for attribution on any skill adapted from
another source — `thesis-tracker` is; the other three were built
Minty-native.
