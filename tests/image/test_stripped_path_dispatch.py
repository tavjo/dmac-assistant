"""Wave-3 carryover #2 final check: stripped-PATH dispatch end-to-end.

Runs inside dmac-assistant:poc. Invokes nextseek-entity-extract and
nextseek-api-read shim binaries with PATH=/usr/bin:/bin (the same
stripped-PATH form used by Wave-3 dispatch tests B04/B05/B06a/B06b/B07/B08).

This is a WIRING test (subprocess-based). It does NOT contribute to
_nextseek_runner.py coverage measurement.
"""
from __future__ import annotations

import json
import subprocess
import os


STRIPPED_PATH_ENV = {
    "PATH": "/usr/bin:/bin",
    "API_USER": "testuser",
    "API_PASS": "testpass",
    "NEXTSEEK_DRY_RUN": "1",
}


def test_entity_extract_dispatches_under_stripped_path():
    merged = {**os.environ, **STRIPPED_PATH_ENV}
    r = subprocess.run(
        ["/app/plugins/nextseek/bin/nextseek-entity-extract", "--query", "test"],
        capture_output=True,
        text=True,
        env=merged,
    )
    assert r.returncode == 0, (
        f"nextseek-entity-extract failed under stripped PATH=/usr/bin:/bin "
        f"(exit={r.returncode}). stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    payload = json.loads(r.stdout)
    assert "sampletypes" in payload


def test_api_read_dispatches_under_stripped_path():
    merged = {**os.environ, **STRIPPED_PATH_ENV}
    r = subprocess.run(
        [
            "/app/plugins/nextseek/bin/nextseek-api-read",
            "--parser-plan",
            json.dumps({"endpoint": "/sample/", "method": "GET"}),
        ],
        capture_output=True,
        text=True,
        env=merged,
    )
    assert r.returncode == 0, (
        f"nextseek-api-read failed under stripped PATH=/usr/bin:/bin "
        f"(exit={r.returncode}). stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    payload = json.loads(r.stdout)
    assert "endpoint" in payload
