"""Plan B · T2: shared runner produces structured JSON output."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Skip cleanly on hosts without chat_nextseek installed. The subprocess we
# spawn loads `_nextseek_runner.py`, which does
# `from chat_nextseek.config import ChatConfig` first; on a host without
# chat_nextseek that exits 2 with IMPORT_FAILED before reaching the
# cred-missing branch this test asserts. chat_nextseek is image-only by
# Plan A T7's PATH_B decision (host Python 3.12 vs chat_nextseek's
# `requires-python >=3.14`) — see plan `## Host vs Image Python Environment`
# and `## Amendment Log` entry "chat_nextseek host-import audit (2026-05-02)".
pytest.importorskip("chat_nextseek")

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
