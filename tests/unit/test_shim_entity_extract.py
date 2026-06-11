"""Plan B · T3 — nextseek-entity-extract shim.

Image-only by Plan A T7's PATH_B decision: chat_nextseek requires Python ≥3.14
and is never installed on host. The runner is invoked transitively from these
tests' subprocess calls only when the test stubs the runner; the real shim's
--help and missing-arg paths exit before reaching the runner. Per Wave-3
inheritance rule 1 (2026-05-02 chat_nextseek host-import audit item 7),
gate the whole file with importorskip — the rule is unconditional.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# T11 (U-11): the chat_nextseek importorskip gate is GONE — the shim execs
# the thin _nextseek_runner.py (sidecar/viewset client), which imports no
# chat_nextseek. These subprocess tests run on host AND inside the image.

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "nextseek-entity-extract"
COMMON = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    """--help short-circuits before exec'ing the runner. Exit 0, stdout 'Usage'."""
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-entity-extract" in r.stdout


def test_missing_query_errors_with_code_3():
    """Missing --query → nextseek_die 3 'missing --query' on stderr."""
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --query" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    """Stub the runner — confirm shim invokes it with --agent entity --query <text>.

    The real shim execs `python "$SCRIPT_DIR/_nextseek_runner.py" --agent entity
    --query "$QUERY"`. We copy the shim and the common helper into a tmp dir, and
    plant a fake _nextseek_runner.py that echoes argv as JSON. This isolates the
    test from chat_nextseek and from the runner's real dispatch table.
    """
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)

    fake_common = tmp_path / "_nextseek_common.sh"
    fake_common.write_text(COMMON.read_text())

    fake_shim = tmp_path / "nextseek-entity-extract"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    # Preserve PATH so `exec python` in the shim resolves the same interpreter
    # as the test runner. macOS 12+ has no /usr/bin/python (only /usr/bin/python3),
    # so a stripped PATH like {"PATH": "/usr/bin:/bin"} would fail before the fake
    # runner runs. See §9.3 for the full rationale.
    import os
    env = {**os.environ, "API_USER": "x", "API_PASS": "y"}
    r = subprocess.run(
        [str(fake_shim), "--query", "find LinVo samples"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert payload["called_with"][0] == "--agent"
    assert payload["called_with"][1] == "entity"
    assert payload["called_with"][2] == "--query"
    assert payload["called_with"][3] == "find LinVo samples"
