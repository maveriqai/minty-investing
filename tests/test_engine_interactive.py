"""Tests for engine/interactive.py's _save_composed_outputs — the generic
"engine writes the .md deliverable" mechanism. Staged skills must be
excluded: their own run_staged_<skill> tool handler
(engine/staged_skills.py's compose_and_save) already writes this same
file, built from every stage's actual tool calls, not just the outer
turn's own reply — this function seeing it too would silently clobber the
correct file with a worse one (issue #15).
"""

import asyncio

import pytest

import engine.interactive as interactive_module
import engine.skills as skills_module
from engine.interactive import (
    _extract_next_step,
    _render_reply,
    _report_changed_files,
    _save_composed_outputs,
    _split_footer,
    _stream_with_indicator,
    _suspend_input_echo,
)
from engine.sources_footer import FOOTER_MARKER
from engine.time_ist import today_ist

_TODAY = today_ist()


@pytest.fixture(autouse=True)
def _debug_diagnostics(monkeypatch):
    # Every existing test below asserts on _report_changed_files'/
    # _save_composed_outputs' printed diagnostics via capsys — they're
    # testing the underlying matching/save logic, not issue #37's gating
    # behavior itself (which gets its own tests, further down, that
    # explicitly override this).
    monkeypatch.setenv("MINTY_DEBUG", "1")


def _write_skill(skills_root, name, *, staged: bool):
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True)
    lines = [
        "---",
        f"name: {name}",
        "description: test skill",
        "expected_outputs:",
        f'  - "{{workspace}}/results/{name}_{{date}}.json"',
        f'  - "{{workspace}}/results/{name}_{{date}}.md"',
    ]
    if staged:
        lines += ["stages:", "  - id: only", "    instructions: do the thing"]
    lines.append("---")
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\nBody.\n")


def _patch_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(skills_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(skills_module, "SKILLS_ROOT", tmp_path / ".claude" / "skills")


def test_save_composed_outputs_skips_a_staged_skill(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    _write_skill(tmp_path / ".claude" / "skills", "staged-skill", staged=True)
    results_dir = tmp_path / "workspace" / "results"
    results_dir.mkdir(parents=True)
    json_output = results_dir / f"staged-skill_{_TODAY}.json"
    json_output.write_text("{}")

    _save_composed_outputs(
        "outer turn's own thinner reply",
        [str(json_output)],
        ["staged-skill"],
        workspace_name="workspace",
        date=_TODAY,
    )

    assert not (results_dir / f"staged-skill_{_TODAY}.md").exists()


def test_save_composed_outputs_still_saves_a_non_staged_skill(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    _write_skill(tmp_path / ".claude" / "skills", "plain-skill", staged=False)
    results_dir = tmp_path / "workspace" / "results"
    results_dir.mkdir(parents=True)
    json_output = results_dir / f"plain-skill_{_TODAY}.json"
    json_output.write_text("{}")

    _save_composed_outputs(
        "the full composed brief",
        [str(json_output)],
        ["plain-skill"],
        workspace_name="workspace",
        date=_TODAY,
    )

    saved = results_dir / f"plain-skill_{_TODAY}.md"
    assert saved.read_text() == "the full composed brief"


def test_save_composed_outputs_skips_a_per_key_wildcard_md_pattern(tmp_path, monkeypatch):
    # Real bug found live 2026-08-31 (research-notes-bridge testing):
    # thesis-tracker declares "{workspace}/theses/*.md" (issue #44) so
    # _report_changed_files/match_changed_files recognize a real
    # theses/<SYMBOL>.md write as accounted for — but resolve_pattern only
    # substitutes {workspace}/{date}, leaving the "*" literal. Before this
    # fix, that meant _save_composed_outputs wrote the turn's full reply
    # text to a file literally named "*.md" every single new-thesis turn,
    # instead of leaving the real per-symbol file (already written by
    # update_workspace_notes) alone.
    skill_dir = tmp_path / ".claude" / "skills" / "wildcard-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: wildcard-skill\n"
        "description: test skill\n"
        "expected_outputs:\n"
        '  - "{workspace}/results/wildcard-skill_{date}.json"\n'
        '  - "{workspace}/theses/*.md"\n'
        "---\n"
        "Body.\n"
    )
    _patch_roots(monkeypatch, tmp_path)
    results_dir = tmp_path / "workspace" / "results"
    results_dir.mkdir(parents=True)
    json_output = results_dir / f"wildcard-skill_{_TODAY}.json"
    json_output.write_text("{}")
    theses_dir = tmp_path / "workspace" / "theses"
    theses_dir.mkdir(parents=True)
    real_thesis = theses_dir / "RELIANCE.md"
    real_thesis.write_text("the real, curated scorecard")

    _save_composed_outputs(
        "the turn's full informal reply, not the curated scorecard",
        [str(json_output), str(real_thesis)],
        ["wildcard-skill"],
        workspace_name="workspace",
        date=_TODAY,
    )

    assert not (theses_dir / "*.md").exists()
    assert real_thesis.read_text() == "the real, curated scorecard"


def test_report_changed_files_omits_raw_data_captures_from_unmatched(tmp_path, monkeypatch, capsys):
    # data/account_identity.json (install-wide) and workspace/data/holdings_*.json
    # (per-skill raw captures, engine/tool_capture.py) are never a skill's own
    # expected_outputs — those always live under results/ — so printing them as
    # "not matching any known skill's expected output" is misleading noise, not
    # a real signal (issue #3). Filtered out by the exact known capture dirs,
    # anchored to REPO_ROOT/workspace_root, not by directory name alone.
    monkeypatch.setattr(interactive_module, "REPO_ROOT", tmp_path)
    identity_file = tmp_path / "data" / "account_identity.json"
    holdings_file = tmp_path / "workspace" / "data" / "holdings_2026-08-25.json"

    _report_changed_files([str(identity_file), str(holdings_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" not in out


def test_report_changed_files_omits_the_session_transcript_from_unmatched(tmp_path, monkeypatch, capsys):
    # workspace/sessions/<timestamp>.md (engine/session_transcript.py, issue
    # #13) is also engine-managed, not a skill's expected_outputs — every
    # turn appends to it, so without this filter it would print as
    # unmatched noise on every single turn.
    monkeypatch.setattr(interactive_module, "REPO_ROOT", tmp_path)
    transcript_file = tmp_path / "workspace" / "sessions" / "2026-08-25T09-00-00.md"

    _report_changed_files([str(transcript_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" not in out


def test_report_changed_files_omits_memory_candidates_from_unmatched(tmp_path, monkeypatch, capsys):
    # workspace/memory_candidates.md (engine/memory_candidates.py, issue
    # #14) is also engine-managed, not a skill's expected_outputs — any
    # ordinary turn where the model calls stage_memory_candidate would
    # otherwise print as unmatched noise (found in review of issue #14).
    monkeypatch.setattr(interactive_module, "REPO_ROOT", tmp_path)
    candidates_file = tmp_path / "workspace" / "memory_candidates.md"

    _report_changed_files([str(candidates_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" not in out


def test_report_changed_files_still_flags_a_stray_file_at_the_workspace_root(tmp_path, monkeypatch, capsys):
    # Exempting memory_candidates.md must be an exact-file match, not a
    # blanket exemption for anything directly in workspace_root — that
    # would also hide a genuinely stray file dropped at the workspace
    # root (found in review of issue #14).
    monkeypatch.setattr(interactive_module, "REPO_ROOT", tmp_path)
    stray_file = tmp_path / "workspace" / "unexpected_top_level.md"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" in out
    assert str(stray_file) in out


def test_report_changed_files_still_flags_a_stray_file_in_a_coincidentally_named_dir(
    tmp_path, monkeypatch, capsys
):
    # A file landing in *some* directory literally named "sessions" that
    # isn't the actual <workspace_root>/sessions capture location (e.g. a
    # skill bug writing into results/some-skill/sessions/) must still be
    # flagged as a genuine surprise, not silently hidden just because its
    # parent directory happens to share a name with the real capture dir
    # (issue #13 review — the filter must be anchored, not name-only).
    monkeypatch.setattr(interactive_module, "REPO_ROOT", tmp_path)
    stray_file = tmp_path / "workspace" / "results" / "some-skill" / "sessions" / "stray.json"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" in out
    assert str(stray_file) in out


def test_report_changed_files_still_reports_a_genuinely_unmatched_file(tmp_path, capsys):
    stray_file = tmp_path / "workspace" / "results" / "unexpected.json"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY)

    out = capsys.readouterr().out
    assert "not matching any known skill's expected output" in out
    assert str(stray_file) in out


def test_report_changed_files_reports_no_files_changed(capsys):
    _report_changed_files([], [], "workspace", date=_TODAY)

    assert capsys.readouterr().out.strip() == "[no files changed this turn]"


# --- Issue #37: diagnostic gating itself (overrides the autouse MINTY_DEBUG=1 above) ---


def test_report_changed_files_stays_silent_on_terminal_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)
    stray_file = tmp_path / "workspace" / "results" / "unexpected.json"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY)

    assert capsys.readouterr().out == ""


def test_report_changed_files_writes_to_the_engine_log_when_given_one(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MINTY_DEBUG", raising=False)
    stray_file = tmp_path / "workspace" / "results" / "unexpected.json"
    log_path = tmp_path / "sessions" / "2026-08-28T09-00-00_engine.log"

    _report_changed_files([str(stray_file)], [], "workspace", date=_TODAY, engine_log_path=log_path)

    assert capsys.readouterr().out == ""
    logged = log_path.read_text(encoding="utf-8")
    assert "not matching any known skill's expected output" in logged
    assert str(stray_file) in logged


# --- Issue #35: the working-indicator wrapper ---


async def _slow_agen(delays_and_values):
    for delay, value in delays_and_values:
        await asyncio.sleep(delay)
        yield value


def test_stream_with_indicator_yields_every_value_in_order():
    async def run():
        return [chunk async for chunk in _stream_with_indicator(_slow_agen([(0, "a"), (0, "b"), (0, "c")]))]

    assert asyncio.run(run()) == ["a", "b", "c"]


def test_stream_with_indicator_writes_spinner_frames_to_stderr_during_a_gap(capsys, monkeypatch):
    monkeypatch.setattr(interactive_module, "_SPINNER_POLL_S", 0.01)

    async def run():
        return [chunk async for chunk in _stream_with_indicator(_slow_agen([(0.05, "a")]))]

    result = asyncio.run(run())

    assert result == ["a"]
    err = capsys.readouterr().err
    assert "working..." in err


def test_stream_with_indicator_clears_the_spinner_line_before_yielding(capsys, monkeypatch):
    monkeypatch.setattr(interactive_module, "_SPINNER_POLL_S", 0.01)

    async def run():
        return [chunk async for chunk in _stream_with_indicator(_slow_agen([(0.05, "a")]))]

    asyncio.run(run())

    err = capsys.readouterr().err
    # The very last write before the chunk is handed back is a clearing
    # line (carriage return, spaces, carriage return) — never left mid-spin.
    assert err.endswith("\r")


def test_stream_with_indicator_propagates_an_empty_generator():
    async def run():
        return [chunk async for chunk in _stream_with_indicator(_slow_agen([]))]

    assert asyncio.run(run()) == []


# --- Issue #42: input-echo suspension ---


def test_suspend_input_echo_is_a_noop_when_stdin_is_not_a_tty():
    # Under pytest, stdin is never a real tty — this exercises the actual
    # no-op path rather than mocking termios away.
    with _suspend_input_echo():
        pass  # must not raise


# --- Issue #39: the trailing "Next: ..." line ---


def test_extract_next_step_pulls_the_trailing_next_line():
    body, next_step = _extract_next_step("Here is the analysis.\n\nNext: want me to go deeper on RELIANCE?")

    assert body == "Here is the analysis."
    assert next_step == "want me to go deeper on RELIANCE?"


def test_extract_next_step_returns_none_when_no_next_line_present():
    body, next_step = _extract_next_step("Just a plain reply, no follow-up.")

    assert body == "Just a plain reply, no follow-up."
    assert next_step is None


def test_extract_next_step_handles_a_next_only_reply():
    body, next_step = _extract_next_step("Next: pick a sector to screen?")

    assert body == ""
    assert next_step == "pick a sector to screen?"


def test_extract_next_step_ignores_next_prefixed_text_mid_paragraph():
    text = "Next: at this point isn't a closing line since more follows.\n\nMore analysis here."

    body, next_step = _extract_next_step(text)

    assert next_step is None
    assert body == text


# --- Issue #38: splitting the model's text from the engine-appended footer ---


def test_split_footer_separates_model_text_from_footer(tmp_path):
    from engine.sources_footer import build_footer

    footer = build_footer(
        [("kite_gateway", "get_holdings", tmp_path / "data" / "holdings_2026-08-28.json")],
        as_of="2026-08-28",
        workspace_root=tmp_path,
    )
    full_text = "Here is your portfolio summary." + footer

    model_text, footer_text = _split_footer(full_text)

    assert model_text == "Here is your portfolio summary."
    assert footer_text == footer
    assert footer_text.startswith(FOOTER_MARKER)


def test_split_footer_returns_the_whole_text_when_no_footer_present():
    model_text, footer_text = _split_footer("Just a plain chat reply.")

    assert model_text == "Just a plain chat reply."
    assert footer_text == ""


def test_split_footer_separates_model_text_from_a_bare_disclaimer():
    """Issue #65: force_disclaimer yields DISCLAIMER_ONLY_FOOTER (no Sources
    list) rather than a full build_footer output — _split_footer must
    recognize that shape too, not just the FOOTER_MARKER one."""
    from engine.sources_footer import DISCLAIMER_ONLY_FOOTER

    full_text = "Here's what's staged for review." + DISCLAIMER_ONLY_FOOTER

    model_text, footer_text = _split_footer(full_text)

    assert model_text == "Here's what's staged for review."
    assert footer_text == DISCLAIMER_ONLY_FOOTER


def test_split_footer_dims_a_self_authored_sources_line_and_disclaimer(tmp_path):
    """Issue #70: a "what are my holdings" reply answered from cached
    data made no fresh captures this turn, so the engine's own footer
    never fired — the model wrote its own "**Sources:** ..." line and the
    disclaimer text itself instead. Both should split out together as one
    footer block, not stay folded into the body as plain undimmed text."""
    from engine.sources_footer import DISCLAIMER

    full_text = (
        "CUPID alone is a quarter of your portfolio.\n\n"
        "**Sources:** Kite holdings snapshot (`workspace/data/holdings_2026-09-03.json`), "
        "computed via `workspace/results/health_check_2026-09-03.json`.\n\n"
        f"{DISCLAIMER}"
    )

    model_text, footer_text = _split_footer(full_text)

    assert model_text.strip() == "CUPID alone is a quarter of your portfolio."
    assert footer_text.startswith("**Sources:**")
    assert footer_text.endswith(DISCLAIMER)


def test_split_footer_dims_a_self_authored_disclaimer_with_no_sources_line(tmp_path):
    """A narrower case than the row above — the model wrote only the
    disclaimer itself, no citation line before it. Only the disclaimer
    sentence should split out; nothing to gain by guessing further back
    into ordinary prose that doesn't start with "**Sources"."""
    from engine.sources_footer import DISCLAIMER

    full_text = f"Here's your answer, no fresh data fetched this turn.\n\n{DISCLAIMER}"

    model_text, footer_text = _split_footer(full_text)

    assert model_text.strip() == "Here's your answer, no fresh data fetched this turn."
    assert footer_text == DISCLAIMER


def test_split_footer_self_authored_fallback_never_fires_when_no_disclaimer_present():
    # Guards against the new fallback swallowing ordinary prose that
    # happens to contain a blank-line-separated paragraph — it must only
    # ever trigger once DISCLAIMER's own exact text is found.
    full_text = "Some body text.\n\n**Sources: not the real thing, just a coincidence.**"

    model_text, footer_text = _split_footer(full_text)

    assert model_text == full_text
    assert footer_text == ""


def test_render_reply_pulls_a_trailing_next_line_out_of_a_self_authored_footer(capsys):
    """A self-authored footer has no fixed engine-appended shape, so the
    model's own trailing `Next: ...` line ends up inside footer_text after
    _split_footer's fallback (issue #70) rather than model_text — found
    live 2026-09-03 retesting the fix: "what are my holdings" answered
    from cached data, wrote its own Sources/disclaimer, then its own
    Next: line right after. Must still land in its own panel, not stay
    stuck inside the dimmed footer block."""
    from engine.sources_footer import DISCLAIMER

    full_text = (
        "Here's your holdings snapshot.\n\n"
        "**Sources:** Kite holdings snapshot (`workspace/data/holdings_2026-09-03.json`).\n\n"
        f"{DISCLAIMER}\n\n"
        "Next: Want the full list, or a deeper look at CUPID?"
    )

    _render_reply(full_text)

    out = capsys.readouterr().out
    assert "Next: Want the full list" not in out
    assert "Want the full list, or a deeper look at CUPID?" in out
    assert "Next" in out
