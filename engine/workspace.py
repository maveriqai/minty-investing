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
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WORKSPACES_ROOT = REPO_ROOT / "workspaces"

# Always watched, every turn, regardless of whether a workspace is active —
# covers both workspace-scoped skills (workspaces/<name>/...) and any
# repo-root-scoped skill's own data/results, without the engine needing to
# know which kind of skill was invoked. See engine/skills.py for the
# per-skill pattern matching this feeds into.
FIXED_WATCH_ROOTS = [REPO_ROOT / "data", REPO_ROOT / "results", WORKSPACES_ROOT]


def resolve_workspace(name: str) -> Path:
    """Creates `workspaces/<name>/{data,results}` if missing — idempotent,
    safe to call every time a workspace is referenced. Returns the
    workspace's root path."""
    root = WORKSPACES_ROOT / name
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)
    return root


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
