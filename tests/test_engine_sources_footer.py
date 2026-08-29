from engine.sources_footer import DISCLAIMER, FOOTER_MARKER, build_footer


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


def test_build_footer_starts_with_the_exported_marker(tmp_path):
    captures = [("kite_gateway", "get_holdings", tmp_path / "data" / "holdings_2026-08-04.json")]

    footer = build_footer(captures, as_of="2026-08-04", workspace_root=tmp_path)

    assert footer.startswith(FOOTER_MARKER)


def test_build_footer_itemizes_a_small_group(tmp_path):
    # 5 distinct candidates for one (server, tool) pair — at the
    # threshold, still itemized (issue #36: only *more than* 5 collapses).
    captures = [
        ("india_price", "get_fundamentals", tmp_path / "data" / f"fundamentals_STOCK{i}_2026-08-28.json")
        for i in range(5)
    ]

    footer = build_footer(captures, as_of="2026-08-28", workspace_root=tmp_path)

    assert footer.count("india_price.get_fundamentals") == 5
    assert "fetched for" not in footer


def test_build_footer_collapses_a_large_group_into_one_summary_line(tmp_path):
    # 25 candidates, one bulk-screen source — issue #36's own live example
    # (screen-indian-stocks over an automotive-sector run).
    captures = [
        ("india_price", "get_fundamentals", tmp_path / "data" / f"fundamentals_STOCK{i}_2026-08-28.json")
        for i in range(25)
    ]

    footer = build_footer(captures, as_of="2026-08-28", workspace_root=tmp_path)

    assert footer.count("india_price.get_fundamentals") == 1
    assert "fetched for 25 candidates" in footer
    assert "STOCK0" not in footer
    assert "STOCK24" not in footer


def test_build_footer_keeps_a_small_group_itemized_alongside_a_collapsed_one(tmp_path):
    # The issue's own scenario: a 25-candidate bulk fetch collapses, but a
    # top-5 in-depth pass on a different tool stays itemized in the same
    # footer — no shared "discussed in depth" signal needed, just group size.
    bulk = [
        ("india_price", "get_fundamentals", tmp_path / "data" / f"fundamentals_STOCK{i}_2026-08-28.json")
        for i in range(25)
    ]
    in_depth = [
        ("india_filings", "get_announcements", tmp_path / "data" / f"announcements_TOP{i}_2026-08-28.json")
        for i in range(3)
    ]

    footer = build_footer(bulk + in_depth, as_of="2026-08-28", workspace_root=tmp_path)

    assert "fetched for 25 candidates" in footer
    assert footer.count("india_filings.get_announcements") == 3
    assert "TOP0" in footer and "TOP1" in footer and "TOP2" in footer


def test_build_footer_group_size_counts_distinct_paths_after_dedup(tmp_path):
    # A retried call to the same path must not inflate the collapsed
    # group's reported count (issue #27/#28's own dedup, still honored).
    path = tmp_path / "data" / "fundamentals_RELIANCE_2026-08-28.json"
    captures = [("india_price", "get_fundamentals", path)] * 10 + [
        ("india_price", "get_fundamentals", tmp_path / "data" / f"fundamentals_STOCK{i}_2026-08-28.json")
        for i in range(6)
    ]

    footer = build_footer(captures, as_of="2026-08-28", workspace_root=tmp_path)

    assert "fetched for 7 candidates" in footer
