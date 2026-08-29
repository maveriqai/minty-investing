"""Reads each skill's own declared `expected_outputs` — glob patterns
(relative to repo root, with `{workspace}`/`{date}` placeholders) stating
what a successful run should produce — and matches them against files that
actually changed.

Declarative, not code: a skill contributor adds one frontmatter field to
their own `SKILL.md` (already at `.claude/skills/<name>/SKILL.md`, see
docs/vision.md §4). The engine's checker (used from `engine/interactive.py`)
is generic — it doesn't know or care which skill was invoked, it just
checks whatever changed against every loaded skill's declared patterns.
This is deliberately not `engine/digest.py`'s old per-skill Python
stage-orchestration: that pattern was built for one skill run unattended,
and doesn't scale to "any contributor can add a skill via a SKILL.md,
no engine code required" (docs/vision.md §2, Track 2).

Not proof the *right* file was written, just that something matching a
declared pattern exists among what changed. A generic presence check, not
full skill-adherence verification.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"


def _parse_frontmatter(skill_md_text: str) -> dict:
    """Parses the YAML frontmatter block between the leading `---` markers.
    Empty dict if there's no frontmatter at all (malformed SKILL.md) rather
    than raising — a skill declaring nothing just isn't checked."""
    if not skill_md_text.startswith("---"):
        return {}
    _, _, rest = skill_md_text.partition("---")
    frontmatter_text, sep, _ = rest.partition("---")
    if not sep:
        return {}
    return yaml.safe_load(frontmatter_text) or {}


def load_expected_outputs(skill_name: str) -> list[str]:
    """Empty list if the skill doesn't exist or declares nothing — not
    every skill needs this yet, and an undeclared skill just isn't
    checked, rather than erroring."""
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return []
    frontmatter = _parse_frontmatter(skill_md.read_text())
    return list(frontmatter.get("expected_outputs") or [])


def load_deterministic_scripts(skill_name: str) -> list[dict]:
    """Each skill's own declared deterministic scripts — the actual
    compute-and-save steps its SKILL.md's procedure describes in prose.

    Empty list if the skill doesn't exist or declares nothing. Shape per
    entry (see engine/skill_tools.py, which turns these into typed,
    per-skill tool calls):

        {"id": "red_flag_check", "path": "scripts/red_flag_check.py",
         "args": [{"name": "symbol", "kind": "flag", "flag": "--symbol",
                    "required": True, "description": "..."}, ...]}

    `kind` is "flag" (emitted as "--flag value") or "positional" (emitted
    in declared order); no ported script currently mixes both kinds.
    """
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return []
    frontmatter = _parse_frontmatter(skill_md.read_text())
    return list(frontmatter.get("deterministic_scripts") or [])


def load_description(skill_name: str) -> str:
    """The skill's own one-paragraph `description` frontmatter field — the
    exact text already authored for native Skill-matching. Reused verbatim
    as the base of a staged skill's dedicated tool description
    (engine/staged_skill_tools.py) so routing quality doesn't regress
    between the two mechanisms. Empty string if the skill doesn't exist or
    declares no description."""
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return ""
    frontmatter = _parse_frontmatter(skill_md.read_text())
    return str(frontmatter.get("description") or "")


def load_skill_body(skill_name: str) -> str:
    """The Markdown body after the frontmatter block — the skill's own
    description, numbered steps, and guardrails. For a staged skill (see
    `load_stages`), this is sent as shared context to *every* stage
    (docs/staged-skill-execution-design.md §4, "the body is not replaced")
    rather than being replaced by the frontmatter. Empty string if the
    skill doesn't exist."""
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return ""
    text = skill_md.read_text()
    if not text.startswith("---"):
        return text
    _, _, rest = text.partition("---")
    _, sep, body = rest.partition("---")
    return body.strip() if sep else text


def _validate_stage_order(skill_name: str, stages: list[dict]) -> None:
    """Raises ValueError for two SKILL.md authoring mistakes, caught at
    load time rather than discovered later as a confusing runtime gap:

    - a stage's `needs` names a file that only a stage at the same or
      later position `produces` (docs/staged-skill-execution-design.md
      §5, "Order validation").
    - a stage declares `critical: true` with no `produces` (issue #52) —
      `run_staged_skill`'s abort check only fires off a stage's own
      `produces` glob check, so a `critical` stage with nothing declared
      there would silently never abort, defeating the point of marking it
      critical in the first place.
    """
    all_produces: set[str] = set()
    for stage in stages:
        all_produces.update(stage.get("produces") or [])
    produced_so_far: set[str] = set()
    for stage in stages:
        if stage.get("critical") and not stage.get("produces"):
            raise ValueError(
                f"{skill_name}: stage {stage.get('id')!r} declares critical: true but no "
                f"produces — a critical stage needs produces so run_staged_skill has "
                f"something to check before deciding whether to abort"
            )
        for need in stage.get("needs") or []:
            if need in all_produces and need not in produced_so_far:
                raise ValueError(
                    f"{skill_name}: stage {stage.get('id')!r} needs {need!r}, "
                    f"which is only produced by a same-or-later stage — "
                    f"check {skill_name}'s SKILL.md `stages` ordering"
                )
        produced_so_far.update(stage.get("produces") or [])


def load_stages(skill_name: str) -> list[dict]:
    """Each skill's own declared `stages` (docs/staged-skill-execution-
    design.md) — splitting what would otherwise be one long turn into
    several fresh, bounded-context sessions. Empty list (not an error) if
    the skill doesn't exist or doesn't declare `stages` — that skill just
    keeps running as one turn, unchanged; staging is opt-in.

    Shape per entry: {"id": str, "instructions": str, "needs": [str, ...],
    "produces": [str, ...]}. `needs`/`produces` reuse `expected_outputs`'s
    own glob-pattern-with-placeholders shape (see `resolve_pattern`); both
    are optional per stage.

    Validates load-time stage ordering every call (see
    `_validate_stage_order`) — cheap (one small YAML re-parse), and keeps
    the check honest if a skill's SKILL.md changes without an engine
    restart, matching every other `load_*` function in this module.
    """
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return []
    frontmatter = _parse_frontmatter(skill_md.read_text())
    stages = list(frontmatter.get("stages") or [])
    if stages:
        _validate_stage_order(skill_name, stages)
    return stages


def load_identity_precheck(skill_name: str) -> bool:
    """Whether skill_name's staged run should run a deterministic
    check_identity_match precheck, in-process, before stage 1's session
    ever opens (issue #51) — a top-level opt-in frontmatter flag
    (`identity_precheck: true`, sibling of `stages:`), not a per-stage
    field like #52's `critical`: it applies once, before any stage starts,
    not to one stage's own outcome.

    False (not an error) if the skill doesn't exist or declares nothing —
    matches every other `load_*` function's convention in this module.
    Harmless if declared on a skill with no `stages`: there'd be no
    `run_staged_<skill>` tool to ever consult it from."""
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return False
    frontmatter = _parse_frontmatter(skill_md.read_text())
    return bool(frontmatter.get("identity_precheck", False))


def load_tool_call_budgets(skill_name: str) -> dict[str, int]:
    """Each skill's own declared per-turn call ceiling for a specific MCP
    tool — e.g. morning-digest's documented "~20 india_news.get_news calls"
    (its Guardrails section), now a fact the engine enforces (see
    engine/tool_budget.py) rather than a number the model has to remember
    and self-police.

    Empty dict if the skill doesn't exist or declares nothing. Keys are
    "<mcp_server>.<tool_name>" (matching how a skill's own prose already
    names a tool, e.g. "india_news.get_news"), values are the max calls to
    that tool permitted in one turn.
    """
    skill_md = SKILLS_ROOT / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return {}
    frontmatter = _parse_frontmatter(skill_md.read_text())
    return dict(frontmatter.get("tool_call_budgets") or {})


def resolve_pattern(pattern: str, *, workspace_name: str | None, date: str) -> str:
    """Substitutes `{date}` always, `{workspace}` only if a workspace name
    is given. A pattern still containing a literal `{workspace}` after this
    (because none was active) is intentionally left unresolved — `glob()`
    on it just won't match anything real, correctly signaling "not
    applicable without an active workspace" rather than raising."""
    resolved = pattern.replace("{date}", date)
    if workspace_name is not None:
        resolved = resolved.replace("{workspace}", workspace_name)
    return resolved


def composed_output_patterns(skill_name: str) -> list[str]:
    """The subset of `skill_name`'s own `expected_outputs` that the engine
    itself should write, rather than a deterministic script — currently:
    anything ending `.md`, a skill's prose deliverable (e.g. morning-
    digest's `results/digest_{date}.md`), as opposed to a `.json` a script
    like `digest_math.py` already wrote as a side effect of computing it.

    No second frontmatter field needed to mark this — the `.md`/`.json`
    split already matches "composed text" vs. "computed data" for every
    skill ported so far. See engine/interactive.py's
    `_save_composed_outputs`, which uses this to know which pattern to
    fill in with a turn's full response text, and `match_changed_files`
    (this same file) to know *whether* to — only once the skill's own
    non-`.md` pattern (its deterministic script's real output) actually
    changed this turn, not on every turn a workspace happens to be open.
    """
    return [p for p in load_expected_outputs(skill_name) if p.endswith(".md")]


def match_changed_files(
    skill_name: str, changed_files: list[str], *, workspace_name: str | None, date: str
) -> list[str]:
    """Which of `changed_files` (absolute path strings) satisfy any of
    `skill_name`'s declared `expected_outputs` patterns."""
    matches: set[str] = set()
    for pattern in load_expected_outputs(skill_name):
        resolved = resolve_pattern(pattern, workspace_name=workspace_name, date=date)
        if "{workspace}" in resolved:
            continue  # needs a workspace that isn't active — can't match anything
        matches.update(str(p) for p in REPO_ROOT.glob(resolved))
    return sorted(f for f in changed_files if f in matches)
