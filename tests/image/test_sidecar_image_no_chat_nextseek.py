"""T17: live_docker gate — sidecar image absence of chat_nextseek + torch.

Proves the T17 image-strip by running import probes inside the built sidecar
image:
  - `import chat_nextseek` must FAIL (exit non-zero)
  - `import torch` must FAIL (exit non-zero)
  - `import sidecar.app.server` must SUCCEED (exit 0)
  - `import httpx` must SUCCEED (exit 0)

Also records and asserts the image size is below a generous ceiling (DD-A5-8).
The ceiling is generous (800 MB) — the gate tests for "torch is gone" not a
precise byte count.

Run: `uv run pytest tests/image/test_sidecar_image_no_chat_nextseek.py \
      -m live_docker -p no:xdist`
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.harness.containers import docker_available

pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.live_docker,
    pytest.mark.slow,
]

_SIDECAR_IMAGE = "dmac-nextseek-sidecar:poc"
# DD-A5-8: generous ceiling (800 MB). Torch alone was ~1.5 GB; without it the
# image should be well under 600 MB. The test is "torch is gone", not exact size.
_IMAGE_SIZE_CEILING_BYTES = 800 * 1024 * 1024  # 800 MB


def _image_exists() -> bool:
    r = subprocess.run(
        ["docker", "images", _SIDECAR_IMAGE, "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return _SIDECAR_IMAGE in r.stdout


def _run_in_image(python_code: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python",
         _SIDECAR_IMAGE, "-c", python_code],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


@pytest.fixture(autouse=True)
def _require_image():
    if not _image_exists():
        pytest.skip(f"{_SIDECAR_IMAGE} not built; run `make sidecar-build` first")


def test_chat_nextseek_import_fails():
    """T17: chat_nextseek must be ABSENT from the sidecar image (A-5)."""
    result = _run_in_image("import chat_nextseek")
    assert result.returncode != 0, (
        "Expected `import chat_nextseek` to FAIL inside the sidecar image "
        "(chat_nextseek was stripped in T17, A-5) but it returned exit 0. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_torch_import_fails():
    """T17: torch must be ABSENT from the sidecar image (A-5)."""
    result = _run_in_image("import torch")
    assert result.returncode != 0, (
        "Expected `import torch` to FAIL inside the sidecar image "
        "(torch was stripped in T17, A-5) but it returned exit 0. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_sidecar_server_imports_succeed():
    """T17: the sidecar's own server must still be importable (build coherence)."""
    result = _run_in_image(
        "import sidecar.app.server; print('server OK')", timeout=60
    )
    assert result.returncode == 0, (
        "Expected `import sidecar.app.server` to succeed but it failed. "
        f"stderr:\n{result.stderr}"
    )


def test_httpx_imports_succeed():
    """T17: httpx must be present (was transitive-only via chat_nextseek; now explicit)."""
    result = _run_in_image("import httpx; print('httpx OK')")
    assert result.returncode == 0, (
        "Expected `import httpx` to succeed (httpx is now an explicit dep "
        "in sidecar/Dockerfile) but it failed. "
        f"stderr:\n{result.stderr}"
    )


def test_image_size_below_ceiling():
    """T17 DD-A5-8: record actual image size; assert below the generous 800 MB ceiling."""
    r = subprocess.run(
        ["docker", "inspect", _SIDECAR_IMAGE, "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    data = json.loads(r.stdout)
    if isinstance(data, list):
        data = data[0]
    size_bytes = data.get("Size", data.get("VirtualSize", 0))
    size_mb = size_bytes / (1024 * 1024)

    # Persist to evidence/ (gitignored) — T17 spec says record image size there.
    evidence_dir = Path(__file__).resolve().parents[2] / "evidence" / "t17-image-size"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "sidecar_image_size.txt").write_text(
        f"Image: {_SIDECAR_IMAGE}\n"
        f"Size bytes: {size_bytes}\n"
        f"Size MB: {size_mb:.1f}\n"
        f"Ceiling MB: {_IMAGE_SIZE_CEILING_BYTES / (1024*1024):.0f}\n",
        encoding="utf-8",
    )

    assert size_bytes < _IMAGE_SIZE_CEILING_BYTES, (
        f"Sidecar image size {size_mb:.1f} MB exceeds {_IMAGE_SIZE_CEILING_BYTES // (1024*1024)} MB ceiling. "
        "This suggests torch may still be present. Check that T17 edits landed correctly."
    )
    print(f"\nSidecar image size: {size_mb:.1f} MB (ceiling: {_IMAGE_SIZE_CEILING_BYTES // (1024*1024)} MB) — PASS")
