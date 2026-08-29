"""Engine orchestration for skills that declare `stages` (SKILL.md
frontmatter — see `engine/skills.py`'s `load_stages`): splits what would
be one long, unbounded-context turn into several fresh sessions, each
starting from a small, deliberately bounded prompt.

Built to fix the bug documented in full in
docs/staged-skill-execution-design.md: a real 98-holding morning-digest
run made ~70 tool calls in one turn over ~31 minutes, and 11 of 29
`india_news.get_news` results never made it into the Sources footer even
though the underlying files were written correctly — the turn's own
capture bookkeeping lost track of them somewhere in that much context.
Each stage here is small enough that the same failure mode shouldn't have
room to reproduce; see the design doc's §9 for the caveat that this is a
mitigation whose effectiveness at `news_and_materiality`'s own ~36-call
scale hasn't been targeted-repro'd yet.

Deliberately generic, not `morning-digest`-specific: the SKILL.md
frontmatter is the only per-skill input, mirroring `engine/skill_tools.py`'s
own "generic tool factory, not per-skill engine code" pattern.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine import skills
from engine.harnesses.base import Harness, ToolConfig
from engine.sources_footer import DISCLAIMER, build_footer
from engine.time_ist import today_ist
from engine.tool_audit import append_tool_calls, new_audit_log_path
from engine.workspace import augment_prompt_with_workspace

# Subtracted from a staged run's own start time before comparing it to a
# `needs`/`produces` file's mtime (see `run_staged_skill`'s `min_mtime`
# use) — absorbs filesystem mtime-rounding and the gap between capturing
# `run_started_at` and a fast stage's first write. Not a real risk on this
# repo's target OS (APFS is sub-second), but cheap insurance; irrelevant to
# the case this exists for — telling a same-day file from *this* run apart
# from one left over from a run hours earlier — where the gap is orders of
# magnitude larger than this slack.
_FRESHNESS_SLACK_SECONDS = 2.0


def _exists(resolved_pattern: str, *, min_mtime: float | None = None) -> bool:
    """`resolved_pattern` is a repo-root-relative path/glob, already run
    through `skills.resolve_pattern` — matches the glob-based existence
    check `expected_outputs`/`match_changed_files` already use, rather
    than a plain `Path.exists()`, so a `needs`/`produces` entry can use a
    wildcard the same way `expected_outputs` can.

    `min_mtime`, when given, requires a match to have been written at or
    after that time — not just to exist. Without this, a `needs`/`produces`
    check can't tell "this run's stage actually wrote this file" from "a
    file with this exact name is already sitting there from an earlier
    run, same date tag" — live-observed 2026-08-29 (issue #52): a stage
    that correctly declined to write its output because of a detected
    account-identity mismatch was still reported as having succeeded,
    because an hours-old file from a legitimate earlier run that day
    happened to already exist at that same path."""
    matches = skills.REPO_ROOT.glob(resolved_pattern)
    if min_mtime is None:
        return any(matches)
    return any(p.stat().st_mtime >= min_mtime for p in matches)


def _workspace_name(workspace_root: Path) -> str:
    """`workspace_root`'s own path relative to REPO_ROOT ("workspace", or
    ".dev-workspaces/<name>" under MINTY_WORKSPACE) — what a skill's own
    `{workspace}`-placeholder patterns substitute in. Falls back to the
    bare directory name if `workspace_root` isn't under this repo at all
    (a test double standing in for a real workspace)."""
    try:
        return str(workspace_root.relative_to(skills.REPO_ROOT))
    except ValueError:
        return workspace_root.name


def _build_stage_prompt(
    skill_body: str, stage: dict[str, Any], *, present: list[str], missing: list[str]
) -> str:
    """Full SKILL.md body (shared context, every stage) + this stage's own
    authored `instructions`, per docs/staged-skill-execution-design.md §4
    ("the body is not replaced — it's shared context, sent to every
    stage"). `needs` files are listed as paths only, never inlined content
    — see §5, "`_build_stage_prompt`'s contents" — so a stage that needs a
    prior stage's output reads it itself with the Read tool, rather than
    reopening the exact context-bloat problem staging exists to close.
    """
    parts = [skill_body.strip(), "", f"--- Stage: {stage['id']} ---", stage["instructions"].strip()]
    if present or missing:
        parts.append("")
        parts.append("Prior-stage files for this stage:")
        for path in present:
            parts.append(f"- present: {path}")
        for path in missing:
            parts.append(f"- MISSING (that stage did not produce it — say so explicitly, don't guess): {path}")
    return "\n".join(parts)


async def run_staged_skill(
    harness: Harness,
    tools: ToolConfig,
    skill_body: str,
    stages: list[dict[str, Any]],
    *,
    workspace_root: Path,
    date: str,
    now: Callable[[], float] = time.time,
) -> tuple[str, list[tuple[str, str, Path]]]:
    """Runs each declared stage as its own fresh session — a new
    `harness.open_session()` connection per stage, not just a new
    `send()` on one session, since only a new connection actually resets
    accumulated context (§5's "critical, non-obvious detail"). Returns the
    final stage's text (ordinarily `compose`'s — see the `critical` note
    below) and every stage's captures concatenated, for the caller to
    build one aggregated Sources footer from and save (§6 — one footer for
    the whole run, not one per stage).

    Partial-stage failure is fail-open by default (§9, decided
    2026-08-05): a stage whose declared `produces` files don't land —
    whether it raised or just silently didn't write them — is recorded as
    failed, and the next stage's prompt is built listing that gap
    explicitly via `missing`, rather than assuming every prior stage
    succeeded. A stage's own `produces`/`needs` check only counts a file
    written at or after this run's own start (`now`, `min_mtime` on
    `_exists`) — otherwise a same-named file left over from an earlier run
    that day reads as "present" regardless of what this run's stage
    actually did (issue #52).

    A stage may opt out of fail-open by declaring `critical: true` in its
    SKILL.md frontmatter (checked at load time by
    `engine/skills.py::_validate_stage_order` — a `critical` stage with no
    `produces` is rejected there as a no-op). When a `critical` stage's own
    `produces` check fails, the remaining stages never run: this function
    returns immediately with *that stage's own session text* as the final
    text, instead of the usual last-stage-wins text, since no later stage
    (in particular `compose`) will ever run to say anything. This is the
    fix for issue #52, live-observed 2026-08-29: `morning-digest`'s stage 1
    correctly detected and refused to proceed past an account-identity
    mismatch, but stages 2-4 ran anyway on a stale-but-present digest file
    from hours earlier, and the user never saw any indication anything was
    wrong — only the last (`compose`) stage's text ever reached them.

    A stage whose own session raises partway through `send()` is caught
    and treated the same as one that silently didn't write its `produces`
    files — printed, recorded as failed, `text` set to a short synthesized
    note — rather than propagating out and crashing the whole staged run.
    (This was previously documented, inaccurately, as already being the
    case — see the design doc's §9 history.)

    Each stage's own tool calls are written to their own audit log
    (`engine/tool_audit.py`, issue #47) — live-observed 2026-08-29: without
    this, a staged run's per-stage tool calls (e.g. whether a given stage
    actually called `check_identity_match` before fetching holdings) were
    silently unrecoverable after the fact, since `ClaudeAgentSDKHarness.run()`
    and `engine/interactive.py`'s `_repl` were the only two callers that
    ever persisted `session.last_tool_calls` — this function computed it
    (every session does) but never wrote it down. Named by each stage's
    own start time (same convention `run()` uses for a single-shot call),
    not by one shared timestamp for the whole staged run — two stages that
    happen to start within the same second will share a file (append, not
    overwrite), which is fine: the goal is that every stage's tool calls
    end up recoverable and in order, not a strict one-file-per-stage
    guarantee.
    """
    # include_staged_tools=False: a stage's own session must never see
    # run_staged_<skill> itself, or the model could recursively re-trigger
    # the whole staged run from inside one of its own stages.
    stage_tools = dataclasses.replace(tools, include_staged_tools=False)

    all_captures: list[tuple[str, str, Path]] = []
    stage_status: dict[str, bool] = {}
    final_text = ""
    total_cost_usd = 0.0
    total_duration_ms = 0
    total_tokens = 0
    stages_run = 0
    run_started_at = now()
    min_mtime = run_started_at - _FRESHNESS_SLACK_SECONDS

    # workspace_name is workspace_root's own path relative to REPO_ROOT
    # ("workspace", or ".dev-workspaces/<name>" under MINTY_WORKSPACE), not
    # just its directory name — SKILL.md's own `needs`/`produces` patterns
    # are `"{workspace}/results/..."`, with no separate "workspaces/"
    # prefix to reintroduce (docs/next-phase-plan.md §4: one fixed,
    # unnamed workspace, no naming decision left anywhere).
    for stage in stages:
        stages_run += 1
        needed = [
            skills.resolve_pattern(p, workspace_name=_workspace_name(workspace_root), date=date)
            for p in stage.get("needs", [])
        ]
        present = [p for p in needed if _exists(p, min_mtime=min_mtime)]
        missing = [p for p in needed if not _exists(p, min_mtime=min_mtime)]
        # Augmented the same way engine/interactive.py's _run_turn augments
        # every other session's prompt — without this, a stage nudged by
        # the always-on update_workspace_notes/stage_memory_candidate
        # system-prompt instructions has no reliable workspace_root to cite
        # (found in review of issue #14).
        prompt = augment_prompt_with_workspace(
            _build_stage_prompt(skill_body, stage, present=present, missing=missing), workspace_root
        )

        duration_ms = 0
        cost_usd = 0.0
        tokens = 0
        async with harness.open_session(stage_tools) as session:
            text = ""
            try:
                async for chunk in session.send(prompt, workspace_root=workspace_root):
                    text += chunk
            except Exception as exc:  # noqa: BLE001 - a stage failing must not crash the whole run
                print(f"[stage] {stage['id']}: raised {exc!r}", file=sys.stderr)
                text = f"Stage {stage['id']} failed to complete: {exc}"

            all_captures.extend(session.last_captures)
            final_text = text  # ordinarily overwritten by later stages — see the critical-abort return below
            for line in session.last_over_budget:
                print(f"[stage {stage['id']}] [budget] {line}")
            try:
                # getattr, not a raw attribute access — matches
                # engine/interactive.py's own defensive read of this same
                # attribute, so a test double standing in for a real
                # session doesn't need to carry it.
                append_tool_calls(new_audit_log_path(workspace_root), getattr(session, "last_tool_calls", []))
            except OSError as exc:
                # Audit-only side effect — must never take the staged run
                # down with it (same convention as ClaudeAgentSDKHarness.run()).
                print(f"[audit] couldn't write stage {stage['id']}'s tool-call log: {exc}", file=sys.stderr)

            expected = [
                skills.resolve_pattern(p, workspace_name=_workspace_name(workspace_root), date=date)
                for p in stage.get("produces", [])
            ]
            stage_status[stage["id"]] = (
                all(_exists(p, min_mtime=min_mtime) for p in expected) if expected else True
            )

            # EngineResult.raw is the harness-native ResultMessage, which
            # already carries duration_ms/total_cost_usd/usage per SDK
            # session — a read, not new instrumentation (§5/§9, decided
            # 2026-08-07).
            raw = getattr(session.last_result, "raw", None)
            duration_ms = getattr(raw, "duration_ms", 0) or 0
            cost_usd = getattr(raw, "total_cost_usd", 0.0) or 0.0
            usage = getattr(raw, "usage", None) or {}
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        total_duration_ms += duration_ms
        total_cost_usd += cost_usd
        total_tokens += tokens

        ok = stage_status[stage["id"]]
        if not ok and stage.get("critical"):
            remaining = len(stages) - stages_run
            print(
                f"[stage] {stage['id']}: CRITICAL — expected output missing, "
                f"aborting {remaining} remaining stage(s) "
                f"({duration_ms / 1000:.1f}s, ${cost_usd:.4f}, {tokens} tok)"
            )
            print(
                f"[staged run total] {total_duration_ms / 1000:.1f}s, "
                f"${total_cost_usd:.4f}, {total_tokens} tok across {stages_run} of {len(stages)} stages (aborted)"
            )
            return final_text, all_captures

        print(
            f"[stage] {stage['id']}: "
            f"{'ok' if ok else 'expected output missing'} "
            f"({duration_ms / 1000:.1f}s, ${cost_usd:.4f}, {tokens} tok)"
        )

    print(
        f"[staged run total] {total_duration_ms / 1000:.1f}s, "
        f"${total_cost_usd:.4f}, {total_tokens} tok across {stages_run} of {len(stages)} stages"
    )
    return final_text, all_captures


def compose_and_save(
    final_text: str,
    all_captures: list[tuple[str, str, Path]],
    *,
    skill_name: str,
    workspace_root: Path,
) -> str:
    """Appends the one aggregated Sources footer and writes the skill's
    own composed `.md` `expected_outputs` pattern — done here, by plain
    engine Python, not left for the outer (routing) session to paste the
    tool result back verbatim. This is §8's second requirement for the
    tool-based routing design to be reliable: trusting the outer model to
    faithfully relay a long tool result would just be a new instance of
    the same prose-reliance risk this whole project keeps finding and
    fixing mechanically.

    A no-op past the footer-append if `final_text` is blank, or if the
    skill declares no `.md` expected output — mirrors
    `engine/interactive.py`'s `_save_composed_outputs`.

    Skips appending the footer at all if `final_text` already contains our
    own `DISCLAIMER` text — i.e. the compose stage wrote a closing
    footer/disclaimer of its own despite the skill's `SKILL.md` saying not
    to. That instruction isn't reliably followed (issue #27 found the same
    class of unreliable prose-only compliance already documented for #31),
    so this is the structural backstop: better a stray self-authored
    footer than a visible duplicate of the real one.
    """
    footer = "" if DISCLAIMER in final_text else build_footer(
        all_captures, as_of=today_ist(), workspace_root=workspace_root
    )
    full_text = final_text + footer
    if not full_text.strip():
        return full_text
    date = today_ist()
    for pattern in skills.composed_output_patterns(skill_name):
        resolved = skills.resolve_pattern(
            pattern, workspace_name=_workspace_name(workspace_root), date=date
        )
        if "{workspace}" in resolved:
            continue
        path = skills.REPO_ROOT / resolved
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full_text)
        print(f"[engine saved {skill_name}'s composed output — {path}]")
    return full_text


__all__ = ["compose_and_save", "run_staged_skill"]
