"""Plan B · T2: shared runner produces structured JSON output."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# T11 (U-11): no importorskip — `_nextseek_runner.py` is a thin
# sidecar/viewset client that imports no chat_nextseek, so the
# CONFIG_MISSING guard below is reachable on any host.

RUNNER = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def test_runner_emits_structured_error_on_missing_creds(tmp_path, monkeypatch):
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.delenv("API_PASS", raising=False)
    # Use sys.executable (not bare "python") because macOS dev environments
    # frequently lack a `python` symlink on the minimal /usr/bin:/bin PATH —
    # cross-task review MEDIUM-2.
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--agent", "entity", "--query", "x"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["error"]["code"] == "CONFIG_MISSING"
