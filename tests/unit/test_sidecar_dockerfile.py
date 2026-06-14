"""T17: hermetic Dockerfile content tests for the sidecar image.

Asserts that the sidecar Dockerfile no longer installs torch or chat_nextseek
(dead weight after T16 HTTP-forwarder rewire) and explicitly installs httpx.

No Docker daemon required — pure text inspection of sidecar/Dockerfile.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SIDECAR_DOCKERFILE = (REPO / "sidecar" / "Dockerfile").read_text(encoding="utf-8")


def test_no_torch_in_sidecar_dockerfile():
    """T17 Step 1: torch must be stripped from the sidecar image (A-5, OI-2)."""
    assert "torch" not in SIDECAR_DOCKERFILE, (
        "sidecar/Dockerfile must not install torch — the sidecar no longer runs "
        "chat_nextseek in-process; torch is dead weight (T17, A-5)."
    )


def test_no_chat_nextseek_in_sidecar_dockerfile():
    """T17 Step 1: chat_nextseek must be stripped from the sidecar image (A-5, OI-2)."""
    assert "chat_nextseek" not in SIDECAR_DOCKERFILE, (
        "sidecar/Dockerfile must not COPY or install chat_nextseek — the sidecar "
        "ops are now HTTP forwarders to NExtSEEK (T16); the vendor dir stays on "
        "disk for the bridge but is no longer in the sidecar image (T17, A-5)."
    )


def test_httpx_in_sidecar_dockerfile():
    """T17 Step 1: httpx must be explicitly installed (was only transitive via chat_nextseek)."""
    assert "httpx" in SIDECAR_DOCKERFILE, (
        "sidecar/Dockerfile must explicitly install httpx — it was previously "
        "present only transitively via chat_nextseek (T17, A-5)."
    )
