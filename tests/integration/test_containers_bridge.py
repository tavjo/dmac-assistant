"""T05 opt-in live smoke for the bridge's Docker wrapper.

Requires a reachable Docker daemon and the built `dmac-assistant:poc` image.
Gated by both `live_bridge` and `slow` markers so the default `not live and
not slow` merge gate never selects it.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import (
    BridgeAttachSocket,
    attach,
    start_container,
    stop_and_remove,
)
from tests.harness.live_runner import allow_docker_unix_socket_only


pytestmark = [pytest.mark.live_bridge, pytest.mark.slow]


IMAGE = "dmac-assistant:poc"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    allow_docker_unix_socket_only()
    try:
        import docker as _docker

        client = _docker.from_env(timeout=5)
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture
def live_config(tmp_path) -> BridgeConfig:
    dropbox = tmp_path / "dropbox"
    scratch = tmp_path / "scratch" / "alice"
    claude_root = tmp_path / "claude-users" / "alice" / ".claude"
    project = dropbox / "proj-a"
    output = tmp_path / "output"
    for p in (project, scratch, claude_root, output):
        p.mkdir(parents=True, exist_ok=True)
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={"alice": UserRecord(password="s3cret", projects=["proj-a"])},
        claude_users_root=tmp_path / "claude-users",
        scratch_root=tmp_path / "scratch",
        dropbox_root=dropbox,
        output_root=output,
        catalog_file=catalog,
    )


@pytest.fixture
def live_identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id="alice", password=SecretStr("s3cret"), projects=["proj-a"]
    )


@pytest.mark.skip(
    reason=(
        "Obsoleted by T07 live gate. This test drives the docker-py "
        "`attach_socket` read path which is silent against Docker 29.4.0 "
        "(see scripts/diagnostics/t07_autopsy/README.md probe C) and "
        "read_frame() blocks forever on recv() with no timeout. The "
        "wrapper-plumbing and frame-content contracts are proven by "
        "tests/integration/test_resume_e2e.py under @live_bridge."
    )
)
def test_live_bridge_attach_demuxes_stdout(live_identity, live_config):
    if not _docker_available():
        pytest.skip("docker daemon not reachable")

    allow_docker_unix_socket_only()
    import docker as _docker

    client = _docker.from_env()
    try:
        client.images.get(IMAGE)
    except Exception:
        pytest.skip(f"{IMAGE} not present; build it first")

    bridge_env = {
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        "AWS_BEARER_TOKEN_BEDROCK": os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "x"),
    }

    # Replace command with a cheap echo so we don't require valid Bedrock creds.
    container = start_container(
        live_identity,
        image=IMAGE,
        session_id=None,
        bridge_env=bridge_env,
        config=live_config,
        client=client,
    )
    try:
        # Rewrite: replace with a canary command via docker exec-style run.
        # In practice start_container launches claude; we just verify attach
        # returns the right wrapper and cleanup succeeds.
        sock = attach(container)
        assert isinstance(sock, BridgeAttachSocket)
        # Give claude a moment; then read whatever first frame shows up.
        deadline = time.time() + 10
        frame = None
        while time.time() < deadline:
            frame = sock.read_frame()
            if frame is not None:
                break
        # Any stdout/stderr frame (or None on fast auth-fail EOF) is acceptable
        # for the wrapper-plumbing proof; the load-bearing assertion is that
        # we never surface Docker's raw 8-byte stdcopy header.
        #
        # Frame-presence is best-effort — a live daemon without Bedrock
        # credentials may exit before writing to stdout. T07 owns the
        # load-bearing frame-content assertion under the @live_bridge harness
        # with valid creds; here we only prove the wrapper plumbing.
        if frame is not None:
            stream, payload = frame
            assert stream in ("stdout", "stderr")
            assert isinstance(payload, (bytes, bytearray))
        sock.close()
    finally:
        stop_and_remove(container)
