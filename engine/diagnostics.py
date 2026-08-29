"""Single choke point for the engine's routine, developer-facing
diagnostic lines (`[capture]`, `[budget]`, `[matches ...]`, `[other files
changed...]`, `[engine saved ...]`) — issue #37.

Before this existed, every one of these was a bare `print(...)`, landing
unconditionally in the same terminal stream as the model's own reply —
found live during onboarding testing: a `[capture] rejected ...]` line
and a 25-file `[other files changed...]` dump both printed straight into
an otherwise clean answer, with no way to turn them off and no durable
record once the terminal scrolled past (see `engine/engine_log.py`'s
docstring for why the assumption that stdout was already durably logged
was wrong).

Default (no `MINTY_DEBUG`): silent on the terminal, still durable — via
`log_path`, when the caller has one (a per-session `engine_log.py` file).
Set `MINTY_DEBUG=1` (matching the existing `MINTY_WORKSPACE` env-var
precedent, `engine/workspace.py` — no CLI argument parsing exists
anywhere in this entrypoint to hook into instead): unchanged from before
this issue, printed live, for development.

Deliberately NOT used for `[audit] tool error: ...]` (issue #47) — that
line's whole point is live visibility the moment a tool call comes back
denied or errored, which this gating would defeat.
"""

from __future__ import annotations

import os
from pathlib import Path

from engine.engine_log import append_engine_log


def _debug_enabled() -> bool:
    # Read live, not cached at import time, so tests can toggle it with
    # monkeypatch.setenv without needing to reload this module.
    return os.environ.get("MINTY_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def emit(message: str, *, log_path: Path | None = None) -> None:
    if _debug_enabled():
        print(message)
    if log_path is not None:
        try:
            append_engine_log(log_path, [message])
        except OSError:
            # Diagnostic-only side effect — must never take the primary
            # REPL down with it, same convention as the transcript/audit
            # write guards in engine/interactive.py.
            pass


__all__ = ["emit"]
