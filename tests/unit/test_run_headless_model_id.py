"""R1 — assert run_headless.run_one() accepts model_id and emits it in argv.

Companion to plan llm-router-headless-batch-2026-05-18.md (TDD step R1).

Behavioral contract under test:
1. run_one(..., model_id="<id>") MUST cause the resolved docker argv to
   contain the two adjacent tokens `--model` and `<id>`.
2. run_one(..., model_id=None) — and run_one() with model_id omitted —
   MUST NOT include `--model` anywhere in the docker argv (keeps default
   behavior bit-for-bit, so existing run_batch.py callers are unaffected).
"""
from __future__ import annotations

import pathlib
import subprocess
from types import SimpleNamespace

import pytest

from tools.e2e import run_headless


_SONNET_4_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"


def _make_fake_run(captured: list[list[str]]):
    """Return a stand-in for subprocess.run that records argv and exits 0."""

    def _fake_run(cmd, *args, stdin=None, stdout=None, stderr=None,
                  timeout=None, **kwargs):
        captured.append(list(cmd))
        # subprocess.run normally writes to stdout/stderr handles; our
        # mock leaves them as the empty files run_one already opened so
        # _build_record's stdout JSONL parse sees zero events.
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    return _fake_run


def _baseline_kwargs(tmp_path: pathlib.Path) -> dict:
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text("{}")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    return dict(
        query_text="hello",
        query_id="T-model-id-1",
        image="dmac-assistant:poc",
        env={"NEXTSEEK_USERNAME": "demo", "NEXTSEEK_PASSWORD": "demo"},
        timeout=30,
        output_dir=tmp_path / "out",
        catalog_host_path=catalog,
        scratch_dir=scratch,
        claude_dir=claude_dir,
    )


def _find_adjacent(argv: list[str], flag: str, value: str) -> bool:
    for i in range(len(argv) - 1):
        if argv[i] == flag and argv[i + 1] == value:
            return True
    return False


def test_run_one_accepts_model_id_and_emits_flag(tmp_path, monkeypatch):
    """RED — kwarg not implemented yet; expect TypeError on the call."""
    captured: list[list[str]] = []
    monkeypatch.setattr(
        run_headless.subprocess, "run", _make_fake_run(captured),
    )

    run_headless.run_one(
        **_baseline_kwargs(tmp_path),
        model_id=_SONNET_4_ID,
    )

    assert len(captured) == 1, (
        f"expected exactly one subprocess.run invocation, got {len(captured)}"
    )
    argv = captured[0]
    assert _find_adjacent(argv, "--model", _SONNET_4_ID), (
        f"expected `--model {_SONNET_4_ID}` adjacent in argv; got: {argv}"
    )


def test_run_one_omits_model_flag_when_model_id_is_none(tmp_path, monkeypatch):
    """RED-ish — explicit None must NOT introduce --model (regression guard).

    Will fail with TypeError until G1 lands; after G1 it must stay green.
    """
    captured: list[list[str]] = []
    monkeypatch.setattr(
        run_headless.subprocess, "run", _make_fake_run(captured),
    )

    run_headless.run_one(
        **_baseline_kwargs(tmp_path),
        model_id=None,
    )

    argv = captured[0]
    assert "--model" not in argv, (
        f"--model must not appear when model_id is None; got: {argv}"
    )


def test_run_one_default_behavior_unchanged_when_model_id_omitted(
    tmp_path, monkeypatch,
):
    """Existing callers (run_batch.py) pass no model_id — argv must be
    identical to today (no --model token)."""
    captured: list[list[str]] = []
    monkeypatch.setattr(
        run_headless.subprocess, "run", _make_fake_run(captured),
    )

    run_headless.run_one(**_baseline_kwargs(tmp_path))

    argv = captured[0]
    assert "--model" not in argv, (
        f"--model must not appear when model_id is omitted; got: {argv}"
    )


def test_run_one_empty_model_id_does_not_emit_flag(tmp_path, monkeypatch):
    """Edge: empty string for model_id must not produce `--model ''`."""
    captured: list[list[str]] = []
    monkeypatch.setattr(
        run_headless.subprocess, "run", _make_fake_run(captured),
    )

    run_headless.run_one(
        **_baseline_kwargs(tmp_path),
        model_id="",
    )

    argv = captured[0]
    assert "--model" not in argv, (
        f"empty model_id must not emit --model; got: {argv}"
    )
