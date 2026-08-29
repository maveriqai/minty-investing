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
from pathlib import Path
from typing import Any

from engine import skills
from engine.harnesses.base import Harness, ToolConfig
from engine.sources_footer import DISCLAIMER, build_footer
from engine.time_ist import today_ist
from engine.tool_audit import append_tool_calls, new_audit_log_path
from engine.workspace import augment_prompt_with_workspace


def _exists(resolved_pattern: str) -> bool:
    """`resolved_pattern` is a repo-root-relative path/glob, already run
    through `skills.resolve_pattern` — matches the glob-based existence
    check `expected_outputs`/`match_changed_files` already use, rather
    than a plain `Path.exists()`, so a `needs`/`produces` entry can use a
    wildcard the same way `expected_outputs` can."""
    return any(skills.REPO_ROOT.glob(resolved_pattern))


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
) -> tuple[str, list[tuple[str, str, Path]]]:
    """Runs each declared stage as its own fresh session — a new
    `harness.open_session()` connection per stage, not just a new
    `send()` on one session, since only a new connection actually resets
    accumulated context (§5's "critical, non-obvious detail"). Returns the
    final (compose) stage's text and every stage's captures concatenated,
    for the caller to build one aggregated Sources footer from and save
    (§6 — one footer for the whole run, not one per stage).

    Partial-stage failure is fail-open (§9, decided 2026-08-05): a stage
    whose declared `produces` files don't land — whether it raised or
    just silently didn't write them — is recorded as failed, and the next
    stage's prompt is built listing that gap explicitly via `missing`,
    rather than assuming every prior stage succeeded.

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

    # workspace_name is workspace_root's own path relative to REPO_ROOT
    # ("workspace", or ".dev-workspaces/<name>" under MINTY_WORKSPACE), not
    # just its directory name — SKILL.md's own `needs`/`produces` patterns
    # are `"{workspace}/results/..."`, with no separate "workspaces/"
    # prefix to reintroduce (docs/next-phase-plan.md §4: one fixed,
    # unnamed workspace, no naming decision left anywhere).
    for stage in stages:
        needed = [
            skills.resolve_pattern(p, workspace_name=_workspace_name(workspace_root), date=date)
            for p in stage.get("needs", [])
        ]
        present = [p for p in needed if _exists(p)]
        missing = [p for p in needed if not _exists(p)]
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
            async for chunk in session.send(prompt, workspace_root=workspace_root):
                text += chunk
            all_captures.extend(session.last_captures)
            final_text = text  # only the last (compose) stage's text is the actual digest
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
            stage_status[stage["id"]] = all(_exists(p) for p in expected) if expected else True

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

        print(
            f"[stage] {stage['id']}: "
            f"{'ok' if stage_status[stage['id']] else 'expected output missing'} "
            f"({duration_ms / 1000:.1f}s, ${cost_usd:.4f}, {tokens} tok)"
        )

    print(
        f"[staged run total] {total_duration_ms / 1000:.1f}s, "
        f"${total_cost_usd:.4f}, {total_tokens} tok across {len(stages)} stages"
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
