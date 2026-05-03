"""Plan B · T6a — nextseek-api-read shim.

Image-only per Wave-3 inheritance rule 1. Includes the CRITICAL-3 boundary
test mandated by plan body line 1564-1574: a read shim must NOT accept
--confirmed-write. The runner's L2 allowlist would catch a write attempt
on the read endpoint, but this shim-level rejection means an LLM cannot
silently smuggle --confirmed-write through the L1-allowed read pathway.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-api-read"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-api-read" in r.stdout
    assert "--parser-plan" in r.stdout


def test_missing_parser_plan_errors_with_code_3():
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --parser-plan" in r.stderr
    assert "nextseek-error" in r.stderr


def test_read_shim_rejects_confirmed_write():
    """CRITICAL-3 boundary: read shim must exit non-zero with the specific
    message naming nextseek-api-write as the correct route."""
    r = subprocess.run(
        [str(SHIM),
         "--query", "x",
         "--parser-plan", "{}",
         "--confirmed-write"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0, (
        f"read shim accepted --confirmed-write: stdout={r.stdout!r} "
        f"stderr={r.stderr!r}"
    )
    assert "--confirmed-write is not valid on nextseek-api-read" in r.stderr
    assert "nextseek-api-write" in r.stderr


def test_runner_dispatched_with_correct_args(tmp_path):
    """Stub runner — confirm shim invokes it with --agent api-read --parser-plan
    <json> (and --query if supplied)."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-api-read"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    plan_json = '{"target_endpoint":"/sample/","method":"GET"}'
    r = subprocess.run(
        [str(fake_shim),
         "--query", "list LinVo samples",
         "--parser-plan", plan_json],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "api-read"
    # --parser-plan must be present, with the exact JSON string preserved.
    assert "--parser-plan" in argv
    assert plan_json in argv
    # --query forwarded as well (optional but supported).
    assert "--query" in argv
    assert "list LinVo samples" in argv
    # --confirmed-write MUST NOT be in the forwarded argv.
    assert "--confirmed-write" not in argv
