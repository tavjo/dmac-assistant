"""tools/hibayes/tests/test_stage_a_smoke.py — Makefile target pinning for T4.3."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE_PATH = REPO_ROOT / "Makefile"


def test_makefile_declares_hibayes_stage_a_smoke_target() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert re.search(r"^hibayes-stage-a-smoke:", text, flags=re.MULTILINE), (
        "Makefile missing hibayes-stage-a-smoke target"
    )


def test_smoke_target_runs_in_image() -> None:
    """DD-04: smoke gate runs Stage A inside hibayes-runtime-reliability:dev.

    Asserts the DIRECT `docker run` invocation shape (matching plan BP-9), NOT
    the sibling-axis wrapper `scripts/run_hibayes_eval_artifact.sh`, which does
    not bind-mount `evidence/` and would FileNotFoundError on the reference
    manifest. The substring assertions below are specific enough that the
    runtime-axis wrapper cannot satisfy them.
    """
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    smoke_re = re.compile(
        r"^hibayes-stage-a-smoke:(.*?)(?=\n[A-Za-z_-]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = smoke_re.search(text)
    assert match is not None
    body = match.group(1)
    # Recipe MUST invoke `docker run` directly with the BP-9 shape.
    assert "docker run --rm" in body
    assert "--platform linux/amd64" in body
    assert "hibayes-runtime-reliability:dev" in body or "$(SMOKE_IMAGE)" in body
    # Evidence/ MUST be bind-mounted (the wrapper does NOT mount it).
    assert "/work/evidence:ro" in body
    # PYTHONPATH MUST cover both src/ and tools/ per BP-9.
    assert "PYTHONPATH=/work/src:/work/tools" in body
    # Recipe MUST NOT route through scripts/run_hibayes_eval_artifact.sh — that
    # wrapper does not mount evidence/ and would break the smoke.
    assert "run_hibayes_eval_artifact.sh" not in body
    assert "run_hibayes_eval.sh" not in body


def test_smoke_target_does_not_overload_locked_artifact_target() -> None:
    """DL-020: target name is `hibayes-stage-a-smoke`, NOT `hibayes-eval-artifact-smoke`."""
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "hibayes-eval-artifact-smoke" not in text


def test_smoke_target_declares_hibayes_eval_build_order_only() -> None:
    """`hibayes-eval-build` MUST appear after `|` (order-only prereq).

    Pattern matches task-14's `test_hibayes_eval_build_is_order_only_prereq` for
    `hibayes-eval-artifact` / `hibayes-eval-functional` / `hibayes-combined-report`.
    Order-only avoids retriggering a network + docker-cache check
    (`hibayes-eval-build` is `.PHONY` and runs `git ls-remote`) on every smoke
    invocation, which would break CI portability in offline environments.
    """
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    target_line_re = re.compile(r"^hibayes-stage-a-smoke:[^\n]*", re.MULTILINE)
    match = target_line_re.search(text)
    assert match is not None, "Makefile missing hibayes-stage-a-smoke target line"
    target_line = match.group(0)
    assert "|" in target_line, (
        f"hibayes-stage-a-smoke prereq line missing `|` order-only separator: {target_line!r}"
    )
    pipe_idx = target_line.index("|")
    build_idx = target_line.find("hibayes-eval-build")
    assert build_idx > pipe_idx, (
        f"`hibayes-eval-build` must appear AFTER `|` to be order-only; "
        f"line was {target_line!r}"
    )


def test_smoke_recipe_mkdirs_out_before_docker_run() -> None:
    """Recipe MUST `mkdir -p out` before the `docker run` invocation.

    Without this, on Linux Docker (and some macOS Docker Desktop configurations),
    Docker auto-creates the host-side `out/` as root-owned when the
    `-v $(CURDIR)/out:/work/out:rw` bind-mount target is missing, which then
    breaks subsequent host-side writes / edits / rm. Precedent:
    `scripts/run_hibayes_eval.sh:19` (`mkdir -p "${REPO}/out"`).
    """
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    smoke_re = re.compile(
        r"^hibayes-stage-a-smoke:(.*?)(?=\n[A-Za-z_-]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = smoke_re.search(text)
    assert match is not None
    body = match.group(1)
    assert "mkdir -p out" in body, (
        "hibayes-stage-a-smoke recipe missing `mkdir -p out` before docker run"
    )
    mkdir_idx = body.find("mkdir -p out")
    docker_idx = body.find("docker run")
    assert mkdir_idx >= 0 and docker_idx >= 0
    assert mkdir_idx < docker_idx, (
        "`mkdir -p out` must appear BEFORE `docker run` so the bind-mount target "
        "exists at run time"
    )


@pytest.mark.skipif(shutil.which("make") is None, reason="make absent")
def test_make_dry_run_smoke_target_resolves() -> None:
    """`make --dry-run hibayes-stage-a-smoke` resolves without missing-target errors."""
    result = subprocess.run(
        ["make", "--dry-run", "hibayes-stage-a-smoke"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert "No rule to make target" not in result.stderr
