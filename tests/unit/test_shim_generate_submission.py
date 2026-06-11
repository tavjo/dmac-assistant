"""Plan B · T8 — nextseek-generate-submission shim. Image-only per Wave-3 rule 1."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# T11 (U-11): the chat_nextseek importorskip gate is GONE — the shim execs
# the thin _nextseek_runner.py (sidecar/viewset client), which imports no
# chat_nextseek. These subprocess tests run on host AND inside the image.

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-generate-submission"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-generate-submission" in r.stdout
    assert "--type" in r.stdout
    assert "--uids" in r.stdout


def test_missing_type_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--uids", "UID-1,UID-2"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --type" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_missing_uids_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--type", "GEO"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --uids" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-generate-submission"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    r = subprocess.run(
        [str(fake_shim), "--type", "GEO", "--uids", "UID-1,UID-2,UID-3"],
        capture_output=True,
        text=True,
        # Preserve PATH so `exec python` in the shim resolves the same
        # interpreter as the test runner (macOS has no bare `python` on the
        # minimal /usr/bin:/bin PATH). Pattern from test_shim_entity_extract.
        env={**__import__("os").environ, "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "generate-submission"
    assert "--type" in argv
    assert "GEO" in argv
    assert "--uids" in argv
    assert "UID-1,UID-2,UID-3" in argv
