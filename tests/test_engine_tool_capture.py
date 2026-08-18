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
    ohlcv = capture_path("mcp__india_price__get_daily_ohlcv", {"symbol": "reliance"}, tmp_path)
    news = capture_path("mcp__india_news__get_news", {"query": "reliance"}, tmp_path)

    assert announcements.name == f"announcements_RELIANCE_{_TODAY}.json"
    assert shareholding.name == f"shareholding_RELIANCE_{_TODAY}.json"
    assert fundamentals.name == f"fundamentals_RELIANCE_{_TODAY}.json"
    assert ohlcv.name == "RELIANCE_ohlcv_1y.json"
    assert news.name == f"news_RELIANCE_{_TODAY}.json"


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


def test_capture_path_none_for_uncaptured_tool(tmp_path):
    assert capture_path("mcp__kite_gateway__get_positions", {}, tmp_path) is None
    assert capture_path("Write", {}, tmp_path) is None


def test_capture_path_none_when_required_arg_missing(tmp_path):
    assert capture_path("mcp__india_filings__get_announcements", {}, tmp_path) is None


def test_save_tool_result_writes_file_and_creates_data_dir(tmp_path):
    path = save_tool_result(
        "mcp__kite_gateway__get_holdings", {}, '{"source": "kite", "data": []}', tmp_path
    )
    assert path == tmp_path / "data" / f"holdings_{_TODAY}.json"
    assert path.read_text() == '{"source": "kite", "data": []}'


def test_save_tool_result_overwrites_on_repeat_call(tmp_path):
    save_tool_result("mcp__kite_gateway__get_holdings", {}, "first", tmp_path)
    path = save_tool_result("mcp__kite_gateway__get_holdings", {}, "second", tmp_path)
    assert path.read_text() == "second"


def test_save_tool_result_none_for_uncaptured_tool(tmp_path):
    result = save_tool_result("Write", {"file_path": "x"}, "irrelevant", tmp_path)
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
    save_tool_result("mcp__kite_gateway__get_holdings", {}, '{"data": "first"}', tmp_path)
    path = save_tool_result("mcp__kite_gateway__get_holdings", {}, '{"data": "second"}', tmp_path)
    assert path.read_text() == '{"data": "second"}'
