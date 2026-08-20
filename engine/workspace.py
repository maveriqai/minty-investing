"""Deterministic workspace resolution and change-tracking — the engine's
own responsibility, not left to the model's judgment.

Built after a live red-flag-scan run saved its output entirely outside the
documented workspace path (`test-scan/` at repo root instead of
`workspaces/test-scan/`), and skipped the deterministic script besides.
This doesn't fix skill *adherence* to every procedural step — that needs
the fuller engine-orchestrated version (see `engine/digest.py`'s
stage-split pattern in the old repo, not yet ported here), which knows
each skill's exact expected output and can retry or fail loudly when it's
missing. What this does: removes "which directory" from being a model
decision at all (the engine creates and names it before the model ever
sees the request), and makes the actual outcome — what files really
changed, if any — visible regardless of what the model's own response
claims. A generic presence/absence check, not proof the *right* file was
written; that specificity is what the fuller version adds later.

**One workspace per install (docs/next-phase-plan.md §4).** `WORKSPACE_ROOT`
(`workspace/`, singular) is the one fixed, unnamed workspace a real user
ever sees — no naming decision, no `/workspace <name>` command anywhere in
the product surface. The old multi-workspace machinery (`resolve_workspace`,
below) stays alive only as an internal/dev capability for the kind of test
isolation live-verification runs need, reachable via the `MINTY_WORKSPACE`
env var override (`resolve_active_workspace`), never conversationally.
Its sandbox now lives under `.dev-workspaces/` rather than the old plural
`workspaces/` — kept visibly distinct from the new singular `workspace/`,
which sits right next to it, so the two can't get confused in code, in
`.gitignore` patterns, or in a directory listing.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WORKSPACE_ROOT = REPO_ROOT / "workspace"
DEV_WORKSPACES_ROOT = REPO_ROOT / ".dev-workspaces"

# Always watched, every turn, regardless of which workspace root is active —
# covers both the fixed production workspace and a MINTY_WORKSPACE-overridden
# dev sandbox, without the engine needing to know which kind of run this is.
# See engine/skills.py for the per-skill pattern matching this feeds into.
FIXED_WATCH_ROOTS = [REPO_ROOT / "data", REPO_ROOT / "results", WORKSPACE_ROOT, DEV_WORKSPACES_ROOT]


def resolve_workspace(name: str) -> Path:
    """Creates `.dev-workspaces/<name>/{data,results}` if missing — idempotent,
    safe to call every time. Dev/test-isolation only — never reachable as a
    conversational command; see `resolve_active_workspace`."""
    root = DEV_WORKSPACES_ROOT / name
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)
    return root


def resolve_active_workspace() -> Path:
    """The one workspace root for this run. `MINTY_WORKSPACE=<name>` (dev/test
    isolation only — see this module's own docstring) resolves a named sandbox
    under `.dev-workspaces/`; otherwise this is always the same fixed,
    unnamed `workspace/` — the only workspace a real user's install ever
    has. Idempotent, creates `{data,results}` if missing either way."""
    dev_name = os.environ.get("MINTY_WORKSPACE")
    if dev_name:
        return resolve_workspace(dev_name)
    (WORKSPACE_ROOT / "data").mkdir(parents=True, exist_ok=True)
    (WORKSPACE_ROOT / "results").mkdir(parents=True, exist_ok=True)
    return WORKSPACE_ROOT


def is_within_known_workspace_roots(resolved: Path) -> bool:
    """True if `resolved` is (or is inside) the fixed `WORKSPACE_ROOT` or the
    dev-only `DEV_WORKSPACES_ROOT` sandbox — the membership test every
    model-supplied `workspace_root` argument gets checked against before
    it's trusted as a subprocess cwd or a write target (see
    engine/skill_tools.py, engine/workspace_notes.py)."""
    for root in (WORKSPACE_ROOT.resolve(), DEV_WORKSPACES_ROOT.resolve()):
        if resolved == root or root in resolved.parents:
            return True
    return False


def snapshot(root: Path) -> dict[str, float]:
    """path -> mtime for every file currently under `root`."""
    return {str(p): p.stat().st_mtime for p in root.rglob("*") if p.is_file()}


def changed_since(root: Path, before: dict[str, float]) -> list[str]:
    """Files under `root` that are new or modified since `before` was taken."""
    after = snapshot(root)
    changed = [path for path, mtime in after.items() if path not in before or mtime > before[path]]
    return sorted(changed)


def snapshot_all(roots: list[Path]) -> dict[str, float]:
    """`snapshot()` merged across several roots — missing directories are
    skipped, not an error (e.g. `results/` may not exist until a skill
    first creates it)."""
    combined: dict[str, float] = {}
    for root in roots:
        if root.is_dir():
            combined.update(snapshot(root))
    return combined


def changed_since_all(roots: list[Path], before: dict[str, float]) -> list[str]:
    """`changed_since()` merged across several roots."""
    after = snapshot_all(roots)
    changed = [path for path, mtime in after.items() if path not in before or mtime > before[path]]
    return sorted(changed)
