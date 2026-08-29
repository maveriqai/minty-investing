"""Shared in-process loader for `mcp/kite_gateway/server.py` — used by any
engine-owned SDK tool that needs to call a Kite gateway tool without a real
MCP round trip through the model (issue #46's `fetch_holdings`, issue #48's
`check_identity_match`).

`mcp/` is never imported as a real Python package in this codebase (only
`engine/` is — see CLAUDE.md's Conventions section) — `import
mcp.kite_gateway.server` would collide with the actual installed `mcp` SDK
package that `kite_gateway/server.py` itself depends on (`import mcp.types
as types`, `from mcp.server import Server`, ...). Loaded via
`importlib.util.spec_from_file_location` under a unique module name
instead, the same pattern `tests/test_kite_gateway.py` already uses.
Confirmed safe: `server.py`'s own imports are all absolute references to
the real installed `mcp` package, never this repo's `mcp/common/`, so
nothing here needs `mcp/` to be on `sys.path` as a package.

`@lru_cache` rather than a per-caller module-level load: a fresh module
load mints a fresh in-process `_Upstream()` singleton, discarding the
in-memory session-id cache (still correct, since `_ensure_session_id` falls
back to the persisted file, just wasteful) — and with two callers
(`holdings_fetch.py`, `identity_check.py`) that waste would otherwise
double. One cached load, shared by every caller in this process.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache

from engine.workspace import REPO_ROOT

_KITE_GATEWAY_SERVER_PATH = REPO_ROOT / "mcp" / "kite_gateway" / "server.py"


@lru_cache(maxsize=1)
def get_kite_gateway_server():
    """The loaded `mcp/kite_gateway/server.py` module — `call_tool` is
    directly awaitable once loaded (`@server.call_tool()` is a registration
    decorator that returns the original function unchanged)."""
    spec = importlib.util.spec_from_file_location(
        "kite_gateway_inprocess_server", _KITE_GATEWAY_SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


__all__ = ["get_kite_gateway_server"]
