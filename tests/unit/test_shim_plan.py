"""Plan B · T5 — nextseek-plan shim. Image-only per Wave-3 inheritance rule 1."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# T11 (U-11): the chat_nextseek importorskip gate is GONE — the shim execs
# the thin _nextseek_runner.py (sidecar/viewset client), which imports no
# chat_nextseek. These subprocess tests run on host AND inside the image.

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "nextseek-plan"
COMMON = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-plan" in r.stdout


def test_missing_query_errors_with_code_3():
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --query" in r.stderr
    assert "nextseek-error" in r.stderr


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-plan"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    r = subprocess.run(
        [str(fake_shim), "--query", "what should I do next for project X"],
        capture_output=True,
        text=True,
        # Preserve PATH so `exec python` in the shim resolves the same
        # interpreter as the test runner (macOS has no bare `python` on the
        # minimal /usr/bin:/bin PATH). Pattern from test_shim_entity_extract.
        env={**__import__("os").environ, "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert payload["called_with"][0] == "--agent"
    assert payload["called_with"][1] == "plan"
    assert payload["called_with"][2] == "--query"
    assert payload["called_with"][3] == "what should I do next for project X"
