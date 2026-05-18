"""Pin that the image's /opt/dmac/runner_ns.py matches the source on disk.

Phase 7 follow-up: residual debt #6's real-turn integration tests depend on
`make image-build` having been run AFTER any `container/runner_ns.py` edit.
There is no other CI gate today that catches "developer edited the source
but forgot the rebuild" before integration tests run.

This test reads `container/runner_ns.py` bytes from the working tree and
compares them to `/opt/dmac/runner_ns.py` bytes inside the local
`dmac-assistant:poc` image. Mismatch -> the image is stale and must be
rebuilt with `make image-build`.

Skips cleanly when Docker is unavailable or the image is absent (via the
existing `docker_available` / `ensure_image` helpers).
"""
from __future__ import annotations

from pathlib import Path

import docker
import pytest

from tests.harness.containers import IMAGE_TAG, docker_available, ensure_image


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_PATH = REPO_ROOT / "container" / "runner_ns.py"
IMAGE_PATH = "/opt/dmac/runner_ns.py"


pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.integration,
    pytest.mark.live_docker,
]


@pytest.fixture(scope="module", autouse=True)
def _ensure_image() -> str:
    try:
        return ensure_image()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def _allow_unix_socket():
    try:
        import pytest_socket
    except ImportError:
        yield
        return
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


def test_image_runner_ns_matches_source(_allow_unix_socket: None) -> None:
    """The runner_ns.py baked into the image must match the source on disk.

    When this fails, a developer edited `container/runner_ns.py` and did not
    run `make image-build`. Real-turn integration tests would then exercise
    the OLD bytes despite the source on disk being current, producing
    confusing pass/fail results.
    """
    source_bytes = SOURCE_PATH.read_bytes()
    client = docker.from_env()
    output = client.containers.run(
        image=IMAGE_TAG,
        command=["cat", IMAGE_PATH],
        remove=True,
        stderr=False,
    )
    # docker-py returns bytes for stdout when stream=False (default).
    image_bytes = output if isinstance(output, bytes) else bytes(output)

    if image_bytes == source_bytes:
        return

    # Mismatch — provide a focused diff signal without dumping both files.
    source_size = len(source_bytes)
    image_size = len(image_bytes)
    source_lines = source_bytes.count(b"\n")
    image_lines = image_bytes.count(b"\n")
    source_synthetic = source_bytes.count(b"RunnerSyntheticTerminal")
    image_synthetic = image_bytes.count(b"RunnerSyntheticTerminal")

    pytest.fail(
        "container/runner_ns.py in image does not match source on disk. "
        "Run `make image-build` to rebuild dmac-assistant:poc.\n"
        f"  source: {source_size} bytes, {source_lines} lines, "
        f"{source_synthetic} RunnerSyntheticTerminal matches\n"
        f"  image : {image_size} bytes, {image_lines} lines, "
        f"{image_synthetic} RunnerSyntheticTerminal matches"
    )
