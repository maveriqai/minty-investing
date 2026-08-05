from engine.sources_footer import DISCLAIMER, build_footer


def test_build_footer_returns_empty_string_for_no_captures(tmp_path):
    assert build_footer([], as_of="2026-08-04", workspace_root=tmp_path) == ""


def test_build_footer_lists_each_capture_with_source_label_and_relative_path(tmp_path):
    captures = [
        ("india_filings", "get_shareholding_pattern", tmp_path / "data" / "shareholding_RELIANCE_2026-08-04.json"),
        ("kite_gateway", "get_holdings", tmp_path / "data" / "holdings_2026-08-04.json"),
    ]

    footer = build_footer(captures, as_of="2026-08-04", workspace_root=tmp_path)

    assert "india_filings.get_shareholding_pattern" in footer
    assert "data/shareholding_RELIANCE_2026-08-04.json" in footer
    assert "Kite (Zerodha).get_holdings" in footer
    assert "data/holdings_2026-08-04.json" in footer
    assert "2026-08-04" in footer


def test_build_footer_includes_exact_disclaimer_text(tmp_path):
    captures = [("kite_gateway", "get_holdings", tmp_path / "data" / "holdings_2026-08-04.json")]

    footer = build_footer(captures, as_of="2026-08-04", workspace_root=tmp_path)

    assert DISCLAIMER in footer
    assert "SEBI-registered investment adviser" in DISCLAIMER


def test_build_footer_deduplicates_repeated_saves_to_the_same_path(tmp_path):
    path = tmp_path / "data" / "announcements_RELIANCE_2026-08-04.json"
    captures = [
        ("india_filings", "get_announcements", path),
        ("india_filings", "get_announcements", path),
    ]

    footer = build_footer(captures, as_of="2026-08-04", workspace_root=tmp_path)

    assert footer.count("get_announcements") == 1


def test_build_footer_falls_back_to_absolute_path_when_not_under_workspace_root(tmp_path):
    outside = tmp_path.parent / "elsewhere" / "quote.json"
    captures = [("india_price", "get_quote", outside)]

    footer = build_footer(captures, as_of="2026-08-04", workspace_root=tmp_path)

    assert str(outside) in footer
