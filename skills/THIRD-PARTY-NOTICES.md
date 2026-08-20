# Third-Party Notices

`morning-digest`, `portfolio-health-check`, and `red-flag-scan` were built
Minty-native — no third-party source to attribute. `thesis-tracker` is
adapted; see below.

## thesis-tracker

`.claude/skills/thesis-tracker/SKILL.md` is derived from
[anthropics/financial-services-plugins](https://github.com/anthropics/financial-services-plugins)
(`plugins/vertical-plugins/equity-research/skills/thesis-tracker`),
copyright 2025 Anthropic, PBC, licensed under the Apache License,
Version 2.0 — via
[ginlix-ai/LangAlpha](https://github.com/ginlix-ai/LangAlpha)'s own
adaptation (`skills/thesis-tracker`), also Apache-2.0, which itself notes
this lineage in `skills/THIRD-PARTY-NOTICES.md` of that repo.

Changes made for Minty: wired to real Kite MCP holdings and Minty's own
`india_price`/`india_filings` MCP tools in place of LangAlpha's FMP-backed
data layer; output goes to the active workspace's own
`theses/<SYMBOL>.md` (docs/next-phase-plan.md §4) instead of a Word doc
or shared notes file; price-move math (previously left to prose) runs
through the deterministic `run_thesis_math` SDK tool
(`.claude/skills/thesis-tracker/scripts/thesis_math.py`) instead of a
hand-typed Bash invocation; India-specific conventions (FY quarters, SEBI
disclaimer, no-order-execution guardrail) applied throughout per
`docs/vision.md`.

A copy of the Apache License 2.0 is available at:
http://www.apache.org/licenses/LICENSE-2.0
