"""T4.2 integration test for the router-on Claude Code route."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import docker
import pytest
from fastapi.testclient import TestClient

from dmac_assistant.auth import TokenStore, get_token_store
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.router.baml_client.types import (
    ModelClass,
    Route,
    RouterDecision,
)
from dmac_assistant.router.models import resolve_cc_model
from tests.harness.containers import IMAGE_TAG, docker_available, ensure_image


pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.integration,
]


def _running_image_container_ids() -> set[str]:
    docker_client = docker.from_env()
    return {
        container.id
        for container in docker_client.containers.list(
            all=False, filters={"ancestor": IMAGE_TAG}
        )
        if container.status == "running"
    }


@pytest.fixture(scope="module", autouse=True)
def _ensure_image() -> str:
    """T4.1 must have produced the local image under test."""
    try:
        return ensure_image()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def _allow_unix_socket():
    """Allow AF_UNIX sockets for TestClient and docker-py under pytest-socket."""
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


@pytest.fixture
def bridge_config(tmp_path: Path) -> BridgeConfig:
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={"alice": UserRecord(password="s3cret-alice", projects=["proj-a"])},
        claude_users_root=tmp_path / "claude-users",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        output_root=tmp_path / "output",
        catalog_file=catalog,
        bridge_host="127.0.0.1",
        bridge_port=8000,
    )


@pytest.fixture
def configured_env(
    monkeypatch: pytest.MonkeyPatch, bridge_config: BridgeConfig, tmp_path: Path
) -> None:
    """Publish bridge config and enable the router flag."""
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps({"alice": {"password": "s3cret-alice", "projects": ["proj-a"]}}),
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(bridge_config.claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(bridge_config.scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(bridge_config.dropbox_root))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(bridge_config.output_root))
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(bridge_config.catalog_file))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "stub-token-not-used-cc-mocked")
    monkeypatch.setenv("NEXTSEEK_URL", "https://stub.example.com")
    monkeypatch.setenv("NEXTSEEK_USERNAME", "stub-user")
    monkeypatch.setenv("NEXTSEEK_PASSWORD", "stub-pass")
    monkeypatch.setenv("DMAC_ROUTER_ENABLED", "1")
    # task-04R1: hermetic tests must not depend on the sidecar stack being up.
    # Empty network -> falsy -> start_container skips the fail-fast network
    # check (containers.py:440-455); tmp staging root -> the post-turn staging
    # sweep (which DELETES swept request dirs) can never touch the real default
    # ~/dmac-dev/nextseek-sidecar-staging.
    monkeypatch.setenv("DMAC_SIDECAR_NETWORK", "")
    monkeypatch.setenv("DMAC_SIDECAR_STAGING_ROOT", str(tmp_path / "sidecar-staging"))


@pytest.fixture
def fake_router_agent_cc() -> Any:
    """Deterministic RouterAgent test double for container_cc / sonnet."""

    class _FakeAgent:
        async def route(self, query: str) -> RouterDecision:
            return RouterDecision(
                route=Route.ContainerCC,
                model_class=ModelClass.Sonnet,
                reasoning=f"forced for T4.2 integration test: {query[:8]}",
            )

    return _FakeAgent()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_cc_route_real_container_with_mocked_exec(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
    bridge_config: BridgeConfig,
    fake_router_agent_cc: Any,
    _allow_unix_socket: None,
) -> None:
    """Drive router-on WS dispatch through a real idle container."""
    from dmac_assistant import ws as ws_module
    from dmac_assistant.app import app

    monkeypatch.setattr(ws_module, "_get_router_agent", lambda: fake_router_agent_cc)

    captured_calls: list[dict[str, Any]] = []

    class _MinimalSock:
        def read_frame(self) -> tuple[str, bytes] | None:
            return None

        def close(self) -> None:
            pass

    def _mock_exec_cc_turn(container: Any, **kwargs: Any) -> Any:
        captured_calls.append(kwargs)
        return _MinimalSock()

    monkeypatch.setattr(ws_module, "exec_cc_turn", _mock_exec_cc_turn)

    store: TokenStore = app.dependency_overrides.get(get_token_store, get_token_store)()
    if not isinstance(store, TokenStore):
        store = TokenStore()
    issued = store.issue(
        user_id="alice", password="s3cret-alice", config=bridge_config
    )
    token = issued.token

    frames: list[dict[str, Any]] = []
    before_containers = _running_image_container_ids()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json({"type": "user_message", "content": "test query"})
            for _ in range(20):
                try:
                    frame = ws.receive_json()
                except Exception:
                    break
                frames.append(frame)
                if frame.get("type") in {"route_decided", "session_ended", "error"}:
                    break

    route_decided_frames = [f for f in frames if f.get("type") == "route_decided"]
    assert route_decided_frames, f"no route_decided frame emitted; frames={frames!r}"
    route_frame = route_decided_frames[0]
    assert route_frame["route"] == "container_cc"
    assert route_frame["model_class"] == "sonnet"

    assert captured_calls, "exec_cc_turn was not called"
    # OI-5: CC always dispatches the fixed Opus 4.8 tier (resolve_cc_model),
    # regardless of the model_class the (faked) router returned.
    expected_model_id = resolve_cc_model()
    assert captured_calls[0].get("model_id") == expected_model_id

    await asyncio.sleep(1.5)

    after_containers = _running_image_container_ids()
    leaked = after_containers - before_containers
    assert not leaked, f"router-on path left running container(s): {sorted(leaked)!r}"


def test_configured_env_pins_sidecar_network_and_staging_off(
    configured_env: None, tmp_path: Path
) -> None:
    """task-04R1 regression pin: the hermetic fixture must neutralize sidecar defaults.

    `load_config()` defaults `sidecar_network` to "dmac-nextseek-net"
    (config.py:214) and `start_container` fail-fasts when that network is
    absent (containers.py:440-455). Under `configured_env` the network MUST be
    falsy so the suite can never reach that fail-fast — i.e. gate 14 stays
    deterministic whether or not the sidecar stack is up. The staging root MUST
    live inside the test tmp tree so the destructive post-turn staging sweep
    (ws.py `_sweep_then_diff` -> `sweep_sidecar_staging`, which DELETES swept
    request dirs) can never touch the real default
    ~/dmac-dev/nextseek-sidecar-staging.
    """
    from dmac_assistant.config import load_config

    config = load_config()
    assert config.sidecar_network in (None, ""), (
        "hermetic fixture leaked a truthy sidecar_network — start_container's "
        "network fail-fast is reachable and the suite depends on the sidecar "
        "stack being up"
    )
    assert config.sidecar_staging_root is not None
    assert config.sidecar_staging_root.is_relative_to(tmp_path), (
        "sidecar_staging_root escaped the test tmp tree — the destructive "
        "staging sweep could reach a real staging dir"
    )
