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
