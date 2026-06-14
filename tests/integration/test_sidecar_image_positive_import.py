"""T17 (A-5): image-split gate — REVERSED from T13's positive-import probe.

T17 stripped chat_nextseek + torch from the sidecar image (ops are now HTTP
forwarders to NExtSEEK). This file now asserts the ABSENCE of the heavy runtime
and the PRESENCE of the sidecar's own modules + httpx.

The canonical T17 image-absence test lives at:
    tests/image/test_sidecar_image_no_chat_nextseek.py

This file is retained for historical traceability and runs the same suite of
absence/presence probes so the integration/ directory is consistent.

Run: `uv run pytest tests/integration/test_sidecar_image_positive_import.py \
      -m live_docker -p no:xdist`
"""
from __future__ import annotations

import subprocess

import pytest

from tests.harness.containers import docker_available

pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.live_docker,
    pytest.mark.slow,
]

_SIDECAR_IMAGE = "dmac-nextseek-sidecar:poc"


def _run_in_image(python_code: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python",
         _SIDECAR_IMAGE, "-c", python_code],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


@pytest.fixture(autouse=True)
def _require_image():
    images = subprocess.run(
        ["docker", "images", _SIDECAR_IMAGE, "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if _SIDECAR_IMAGE not in images.stdout:
        pytest.skip(f"{_SIDECAR_IMAGE} not built; run `make sidecar-build` first")


def test_sidecar_image_chat_nextseek_absent() -> None:
    """T17 (A-5): chat_nextseek must be ABSENT from the sidecar image after the strip."""
    result = _run_in_image("import chat_nextseek")
    assert result.returncode != 0, (
        "Expected `import chat_nextseek` to FAIL inside the sidecar image "
        "(chat_nextseek stripped in T17). Got exit 0 — strip may not have landed."
    )


def test_sidecar_image_torch_absent() -> None:
    """T17 (A-5): torch must be ABSENT from the sidecar image after the strip."""
    result = _run_in_image("import torch")
    assert result.returncode != 0, (
        "Expected `import torch` to FAIL inside the sidecar image "
        "(torch stripped in T17). Got exit 0."
    )


def test_sidecar_image_server_importable() -> None:
    """T17: sidecar.app.server must still be importable (build coherence check)."""
    result = _run_in_image(
        "import sidecar.app.server; import httpx; print('OK')", timeout=60
    )
    assert result.returncode == 0, (
        f"sidecar image failed to import sidecar.app.server + httpx "
        f"(exit {result.returncode}); stderr:\n{result.stderr}"
    )
