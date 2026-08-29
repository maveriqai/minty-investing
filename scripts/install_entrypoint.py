"""Gates `uv tool install --editable .` behind a confirmation prompt when
it would silently repoint the global `minty` command away from a
different clone (issue #34) — live-confirmed to actually happen: `uv`
resolves every clone to the identical package identity
`minty-investing==0.1.0` (pyproject.toml), so a second clone's install
silently wins today, with no warning at all.

This performs the actual install itself — not just a passive check —
prompting only when a repoint would happen; a fresh machine or
reinstalling from the same repo proceeds straight through with no prompt.

Usage: uv run python scripts/install_entrypoint.py [--yes]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "minty-investing"
DIST_NAME = PACKAGE_NAME.replace("-", "_")


def _find_existing_install_path() -> Path | None:
    """The repo path the global `minty` currently points at, or None if no
    prior install exists — or it can't be determined, which is treated the
    same way (nothing to conflict with). Read straight from the editable
    install's own direct_url.json — the same place a human has to look to
    diagnose this bug today (see docs/manual-test-runs)."""
    try:
        tools_dir_out = subprocess.run(
            ["uv", "tool", "dir"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    tools_dir = Path(tools_dir_out)
    matches = list(tools_dir.glob(f"{PACKAGE_NAME}/lib/*/site-packages/{DIST_NAME}-*.dist-info/direct_url.json"))
    if not matches:
        return None
    try:
        url = json.loads(matches[0].read_text())["url"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    if not url.startswith("file://"):
        return None
    return Path(url[len("file://") :]).resolve()


def _run_install() -> int:
    return subprocess.run(["uv", "tool", "install", "--editable", "."], cwd=REPO_ROOT, check=False).returncode


def main(argv: list[str]) -> int:
    skip_prompt = "--yes" in argv or "-y" in argv

    existing = _find_existing_install_path()
    if existing is not None and existing != REPO_ROOT and not skip_prompt:
        print(
            f"The global `minty` command currently points at:\n  {existing}\n"
            f"Installing from here will repoint it to:\n  {REPO_ROOT}\n",
            file=sys.stderr,
        )
        try:
            answer = input("Repoint minty to this repo? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print(
                "Aborted — minty still points at the other repo. Run "
                "`uv tool install --editable .` directly, or rerun this "
                "script with --yes, to force it.",
                file=sys.stderr,
            )
            return 1

    return _run_install()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
