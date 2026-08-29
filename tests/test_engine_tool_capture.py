"""Unit tests for engine/tool_capture.py's (server, tool) -> filename
mapping — the raw-input-saving half of skill adherence, complementing
tests/test_engine_skill_tools.py's compute-and-save half.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.tool_capture import capture_path, parse_mcp_tool_name, save_tool_result

_TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def test_parse_mcp_tool_name_splits_server_and_tool():
    assert parse_mcp_tool_name("mcp__india_filings__get_announcements") == ("india_filings", "get_announcements")


def test_parse_mcp_tool_name_none_for_non_mcp_tool():
    assert parse_mcp_tool_name("Write") is None
    assert parse_mcp_tool_name("Bash") is None


def test_parse_mcp_tool_name_none_when_malformed():
    assert parse_mcp_tool_name("mcp__onlyoneserver") is None


def test_capture_path_holdings_needs_no_args(tmp_path):
    path = capture_path("mcp__kite_gateway__get_holdings", {}, tmp_path)
    assert path == tmp_path / "data" / f"holdings_{_TODAY}.json"


def test_capture_path_surveillance_list_uses_lowercased_list_type(tmp_path):
    asm = capture_path("mcp__india_filings__get_surveillance_list", {"list_type": "ASM"}, tmp_path)
    gsm = capture_path("mcp__india_filings__get_surveillance_list", {"list_type": "gsm"}, tmp_path)
    assert asm.name == f"surveillance_asm_{_TODAY}.json"
    assert gsm.name == f"surveillance_gsm_{_TODAY}.json"


def test_capture_path_surveillance_list_defaults_to_asm_when_arg_omitted(tmp_path):
    path = capture_path("mcp__india_filings__get_surveillance_list", {}, tmp_path)
    assert path.name == f"surveillance_asm_{_TODAY}.json"


def test_capture_path_symbol_keyed_tools_uppercase_the_symbol(tmp_path):
    announcements = capture_path(
        "mcp__india_filings__get_announcements", {"symbol": "reliance"}, tmp_path
    )
    shareholding = capture_path(
        "mcp__india_filings__get_shareholding_pattern", {"symbol": "reliance"}, tmp_path
    )
    fundamentals = capture_path("mcp__india_price__get_fundamentals", {"symbol": "reliance"}, tmp_path)
    fundamentals_screener = capture_path(
        "mcp__india_screener__get_fundamentals", {"symbol": "reliance"}, tmp_path
    )
    ohlcv = capture_path("mcp__india_price__get_daily_ohlcv", {"symbol": "reliance"}, tmp_path)
    news = capture_path("mcp__india_news__get_news", {"query": "reliance"}, tmp_path)

    assert announcements.name == f"announcements_RELIANCE_{_TODAY}.json"
    assert shareholding.name == f"shareholding_RELIANCE_{_TODAY}.json"
    assert fundamentals.name == f"fundamentals_RELIANCE_{_TODAY}.json"
    # Deliberately a different filename than india_price's own capture
    # above — the two tools' fundamentals must never overwrite each other,
    # since screen_rank.py (and friends) read both to merge sources.
    assert fundamentals_screener.name == f"fundamentals_screener_RELIANCE_{_TODAY}.json"
    assert ohlcv.name == "RELIANCE_ohlcv_1y.json"
    assert news.name == f"news_RELIANCE_{_TODAY}.json"


def test_capture_path_filing_document_keyed_by_url_basename(tmp_path):
    # issue #25's get_filing_document takes a url, not a symbol — no ticker
    # to key the filename on.
    path = capture_path(
        "mcp__india_filings__get_filing_document",
        {"url": "https://nsearchives.nseindia.com/corporate/SBIN_PressRelease.pdf"},
        tmp_path,
    )
    assert path.name == f"filing_document_SBIN_PressRelease.pdf_{_TODAY}.json"


def test_capture_path_fii_dii_needs_no_args(tmp_path):
    path = capture_path("mcp__india_filings__get_fii_dii_flows", {}, tmp_path)
    assert path.name == f"fii_dii_{_TODAY}.json"


def test_capture_path_get_quote_disambiguates_index_vs_holdings(tmp_path):
    index = capture_path(
        "mcp__india_price__get_quote", {"symbols": ["^NSEI", "^BSESN", "^NSEBANK", "^INDIAVIX"]}, tmp_path
    )
    live = capture_path("mcp__india_price__get_quote", {"symbols": ["RELIANCE", "TCS"]}, tmp_path)
    assert index.name == f"index_quote_{_TODAY}.json"
    assert live.name == f"live_quotes_{_TODAY}.json"


def test_capture_path_get_quote_mixed_symbols_treated_as_holdings(tmp_path):
    # A mix of index and held symbols shouldn't happen per the documented
    # convention (step 4 and 4b are always called separately), but if it
    # ever did, "not all index tickers" should fall through to the more
    # common holdings case rather than silently misfiling under index_quote.
    mixed = capture_path("mcp__india_price__get_quote", {"symbols": ["^NSEI", "RELIANCE"]}, tmp_path)
    assert mixed.name == f"live_quotes_{_TODAY}.json"


def test_capture_path_get_profile_targets_the_fixed_install_wide_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.tool_capture.ACCOUNT_IDENTITY_FILE", tmp_path / "data" / "account_identity.json")
    assert capture_path("mcp__kite_gateway__get_profile", {}, tmp_path) == tmp_path / "data" / "account_identity.json"


def test_capture_path_get_profile_ignores_workspace_root(tmp_path, monkeypatch):
    # Install-wide, not workspace content -- whatever workspace_root is
    # passed shouldn't affect where this lands.
    fixed_path = tmp_path / "data" / "account_identity.json"
    monkeypatch.setattr("engine.tool_capture.ACCOUNT_IDENTITY_FILE", fixed_path)

    one = capture_path("mcp__kite_gateway__get_profile", {}, tmp_path / "workspace-a")
    other = capture_path("mcp__kite_gateway__get_profile", {}, tmp_path / "workspace-b")

    assert one == other == fixed_path


def test_capture_path_get_profile_is_write_once(tmp_path, monkeypatch):
    # The only enforcement this anchor gets: once the file exists, no later
    # get_profile call -- e.g. morning-digest's own step 0 reachability
    # ping -- may touch it again. See engine/tool_capture.py's docstring
    # for why this replaced a model-callable update tool.
    fixed_path = tmp_path / "data" / "account_identity.json"
    monkeypatch.setattr("engine.tool_capture.ACCOUNT_IDENTITY_FILE", fixed_path)
    assert capture_path("mcp__kite_gateway__get_profile", {}, tmp_path) == fixed_path

    fixed_path.parent.mkdir(parents=True)
    fixed_path.write_text('{"data": {"user_id": "AB1234"}}')

    assert capture_path("mcp__kite_gateway__get_profile", {}, tmp_path) is None


def test_save_tool_result_get_profile_writes_once_then_no_ops(tmp_path, monkeypatch):
    fixed_path = tmp_path / "data" / "account_identity.json"
    monkeypatch.setattr("engine.tool_capture.ACCOUNT_IDENTITY_FILE", fixed_path)

    first_body = '{"source": "kite", "as_of": "2026-08-18", "data": {"user_id": "AB1234"}}'
    first = save_tool_result("mcp__kite_gateway__get_profile", {}, first_body, tmp_path)
    assert first == fixed_path
    assert fixed_path.read_text() == first_body

    # A later call -- e.g. a different account's own get_profile, or the
    # same account's step-0 reachability ping -- must not overwrite it.
    second = save_tool_result(
        "mcp__kite_gateway__get_profile",
        {},
        '{"source": "kite", "as_of": "2026-08-18", "data": {"user_id": "ZZ9999"}}',
        tmp_path,
    )
    assert second is None
    assert fixed_path.read_text() == first_body


def test_capture_path_none_for_uncaptured_tool(tmp_path):
    assert capture_path("mcp__kite_gateway__get_positions", {}, tmp_path) is None
    assert capture_path("Write", {}, tmp_path) is None


def test_capture_path_none_when_required_arg_missing(tmp_path):
    assert capture_path("mcp__india_filings__get_announcements", {}, tmp_path) is None


def test_save_tool_result_writes_file_and_creates_data_dir(tmp_path):
    body = '{"source": "kite", "as_of": "2026-08-18", "data": []}'
    path = save_tool_result("mcp__kite_gateway__get_holdings", {}, body, tmp_path)
    assert path == tmp_path / "data" / f"holdings_{_TODAY}.json"
    assert path.read_text() == body


def test_save_tool_result_overwrites_on_repeat_call(tmp_path):
    first = '{"source": "kite", "as_of": "2026-08-18", "data": "first"}'
    second = '{"source": "kite", "as_of": "2026-08-18", "data": "second"}'
    save_tool_result("mcp__kite_gateway__get_holdings", {}, first, tmp_path)
    path = save_tool_result("mcp__kite_gateway__get_holdings", {}, second, tmp_path)
    assert path.read_text() == second


def test_save_tool_result_none_for_uncaptured_tool(tmp_path):
    result = save_tool_result("Write", {"file_path": "x"}, "irrelevant", tmp_path)
    assert result is None
    assert not (tmp_path / "data").exists()


def test_save_tool_result_rejects_non_json_redirect_text(tmp_path, monkeypatch, capsys):
    # issue #24: the Claude Agent SDK's own "exceeds maximum allowed
    # tokens" substitution arrives as an ordinary, non-error tool result —
    # not JSON at all, so it must be rejected outright, not saved verbatim
    # to the exact path a real capture would use.
    # MINTY_DEBUG=1 so the rejection is asserted via stdout here (testing
    # the rejection logic itself) — issue #37's gating of this diagnostic
    # has its own tests below.
    monkeypatch.setenv("MINTY_DEBUG", "1")
    redirect_text = (
        "Error: result (58,237 characters) exceeds maximum allowed tokens. "
        "Output has been saved to /Users/x/tool-results/mcp-india_filings-get_surveillance_list-....txt."
    )
    result = save_tool_result(
        "mcp__india_filings__get_surveillance_list", {"list_type": "ASM"}, redirect_text, tmp_path
    )
    assert result is None
    assert not (tmp_path / "data").exists()
    assert "[capture] rejected" in capsys.readouterr().out


def test_save_tool_result_rejection_is_silent_on_terminal_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)

    save_tool_result("mcp__india_filings__get_surveillance_list", {"list_type": "ASM"}, "not json", tmp_path)

    assert capsys.readouterr().out == ""


def test_save_tool_result_rejection_is_logged_when_an_engine_log_path_is_given(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)
    log_path = tmp_path / "sessions" / "2026-08-28T09-00-00_engine.log"

    save_tool_result(
        "mcp__india_filings__get_surveillance_list",
        {"list_type": "ASM"},
        "not json",
        tmp_path,
        engine_log_path=log_path,
    )

    assert capsys.readouterr().out == ""
    assert "[capture] rejected" in log_path.read_text(encoding="utf-8")


def test_save_tool_result_rejects_json_missing_envelope_keys(tmp_path):
    # Valid JSON, but not the {"source","as_of","data"} contract every
    # Layer-2 tool actually returns -- shouldn't be trusted either.
    result = save_tool_result(
        "mcp__kite_gateway__get_holdings", {}, '{"unexpected": "shape"}', tmp_path
    )
    assert result is None
    assert not (tmp_path / "data").exists()


def test_save_tool_result_skips_a_data_error_envelope(tmp_path):
    # A *successful* MCP call whose payload wraps an application-level
    # failure (NSE timeout etc.) — block.is_error in claude_agent_sdk.py
    # doesn't catch this shape, so it's this function's job to.
    result = save_tool_result(
        "mcp__india_filings__get_surveillance_list",
        {"list_type": "ASM"},
        '{"source": "nse", "as_of": "2026-08-18", "data": {"error": "NSE timeout"}}',
        tmp_path,
    )
    assert result is None
    assert not (tmp_path / "data").exists()


def test_save_tool_result_does_not_let_a_later_error_clobber_a_good_capture(tmp_path):
    good = '{"source": "nse", "as_of": "2026-08-18", "data": [{"symbol": "IRCTC"}]}'
    save_tool_result("mcp__india_filings__get_surveillance_list", {"list_type": "ASM"}, good, tmp_path)
    result = save_tool_result(
        "mcp__india_filings__get_surveillance_list",
        {"list_type": "ASM"},
        '{"source": "nse", "as_of": "2026-08-18", "data": {"error": "NSE timeout"}}',
        tmp_path,
    )
    assert result is None
    assert (tmp_path / "data" / f"surveillance_asm_{_TODAY}.json").read_text() == good


def test_save_tool_result_still_overwrites_on_a_second_successful_call(tmp_path):
    # The existing freshest-wins behavior (test_save_tool_result_overwrites_on_repeat_call)
    # must survive unchanged for genuinely successful repeat calls.
    first = '{"source": "kite", "as_of": "2026-08-18", "data": "first"}'
    second = '{"source": "kite", "as_of": "2026-08-18", "data": "second"}'
    save_tool_result("mcp__kite_gateway__get_holdings", {}, first, tmp_path)
    path = save_tool_result("mcp__kite_gateway__get_holdings", {}, second, tmp_path)
    assert path.read_text() == second
