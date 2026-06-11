"""T13 Step 4 — image-split POSITIVE-import gate (gates 9/10).

The agent-side ABSENCE of chat_nextseek / torch is already gated by T11
(tests/test_image_*; the de-credentialed agent image no longer ships them). This
test proves the COMPLEMENT: the sidecar image DOES carry the heavy NS runtime —
chat_nextseek, torch, the MySQL connector — plus the sidecar's own server + ops
modules. Together with T11 that is the full image-split contract.

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
# Heavy NS runtime that LEFT the agent image (T11) and now lives only here, plus
# the sidecar's own server + portable ops modules (the read-safe context is loaded
# by server import; importing the package modules proves the build is coherent).
_IMPORT_PROBE = (
    "import chat_nextseek, torch, mysql.connector; "
    "import sidecar.app.server; import sidecar.app.ops"
)


def test_sidecar_image_imports_heavy_runtime() -> None:
    """Gate 9/10: `docker run --rm --entrypoint python <sidecar> -c <imports>` -> 0."""
    images = subprocess.run(
        ["docker", "images", _SIDECAR_IMAGE, "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if _SIDECAR_IMAGE not in images.stdout:
        pytest.skip(f"{_SIDECAR_IMAGE} not built; run `make sidecar-build` first")

    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python",
         _SIDECAR_IMAGE, "-c", _IMPORT_PROBE],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == 0, (
        f"sidecar image failed to import the heavy NS runtime "
        f"(exit {result.returncode}); stderr:\n{result.stderr}"
    )
