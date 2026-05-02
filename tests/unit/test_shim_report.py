"""Plan B · T9 — nextseek-report deterministic dispatcher.

Image-only per Wave-3 inheritance rule 1. Single shim with --mode switch over
{samples, protocols, published, rppr}. Runner enforces enum + project
non-empty at _nextseek_runner.py:218-223.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-report"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-report" in r.stdout
    assert "--mode" in r.stdout
    assert "--project" in r.stdout


def test_missing_mode_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--project", "LinVo"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --mode" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_missing_project_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--mode", "samples"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --project" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-report"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    # Preserve PATH so `exec python` in the shim resolves the same interpreter
    # as the test runner. macOS 12+ has no /usr/bin/python — a stripped PATH
    # would break this test before the fake runner runs.
    import os
    env = {**os.environ, "API_USER": "x", "API_PASS": "y"}
    r = subprocess.run(
        [str(fake_shim), "--mode", "samples", "--project", "LinVo"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "report"
    assert "--mode" in argv
    assert "samples" in argv
    assert "--project" in argv
    assert "LinVo" in argv
