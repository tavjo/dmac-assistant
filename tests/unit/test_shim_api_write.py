"""Plan B · T6b — nextseek-api-write shim. Write-class. Image-only per Wave-3
inheritance rule 1. Layer 1 NOT allowlisted (B12). Layer 2 (runner) re-checks
--confirmed-write. Layer 3 is the SKILL.md AskUserQuestion gate (B10)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# T11 (U-11): the chat_nextseek importorskip gate is GONE — the shim execs
# the thin _nextseek_runner.py (sidecar/viewset client), which imports no
# chat_nextseek. These subprocess tests run on host AND inside the image.

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-api-write"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-api-write" in r.stdout
    assert "--parser-plan" in r.stdout
    assert "--confirmed-write" in r.stdout


def test_missing_parser_plan_errors_with_code_3():
    r = subprocess.run([str(SHIM), "--confirmed-write"], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --parser-plan" in r.stderr


def test_missing_confirmed_write_errors_with_code_3():
    """Without --confirmed-write the shim must reject. The runner has its
    own re-check (L2), but the shim's rejection means we never spawn the
    runner subprocess for an unconfirmed write attempt."""
    r = subprocess.run(
        [str(SHIM), "--parser-plan", "{}"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --confirmed-write" in r.stderr


def test_runner_dispatched_with_confirmed_write_forwarded(tmp_path):
    """Stub runner — confirm shim invokes it with --agent api-write,
    --parser-plan <json>, AND --confirmed-write all forwarded."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-api-write"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    plan_json = '{"target_endpoint":"/sample/","method":"POST","requestBody":{}}'
    r = subprocess.run(
        [str(fake_shim),
         "--parser-plan", plan_json,
         "--confirmed-write"],
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
    assert argv[1] == "api-write"
    assert "--parser-plan" in argv
    assert plan_json in argv
    assert "--confirmed-write" in argv
