"""T4.2 integration test for the router-on NExtSEEK route."""
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
from dmac_assistant.router.baml_client.types import Route, RouterDecision
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
    monkeypatch: pytest.MonkeyPatch, bridge_config: BridgeConfig
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
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "stub-not-used-on-ns-path")
    monkeypatch.setenv("NEXTSEEK_URL", "https://stub.example.com")
    monkeypatch.setenv("NEXTSEEK_USERNAME", "stub-user")
    monkeypatch.setenv("NEXTSEEK_PASSWORD", "stub-pass")
    monkeypatch.setenv("DMAC_ROUTER_ENABLED", "1")


@pytest.fixture
def fake_router_agent_ns() -> Any:
    """Deterministic RouterAgent test double for nextseek_query."""

    class _FakeAgent:
        async def route(self, query: str) -> RouterDecision:
            return RouterDecision(
                route=Route.NextseekQuery,
                model_class=None,
                reasoning=f"forced for T4.2 integration test: {query[:8]}",
            )

    return _FakeAgent()


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_ns_route_real_container_empty_query(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
    bridge_config: BridgeConfig,
    fake_router_agent_ns: Any,
    _allow_unix_socket: None,
) -> None:
    """Drive router-on WS dispatch to real runner_ns.py with empty input."""
    from dmac_assistant import ws as ws_module
    from dmac_assistant.app import app

    monkeypatch.setattr(ws_module, "_get_router_agent", lambda: fake_router_agent_ns)

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
            ws.send_json({"type": "user_message", "content": ""})
            for _ in range(30):
                try:
                    frame = ws.receive_json()
                except Exception:
                    break
                frames.append(frame)
                if frame.get("type") == "session_ended":
                    break

    route_decided_frames = [f for f in frames if f.get("type") == "route_decided"]
    assert route_decided_frames, f"no route_decided frame emitted; frames={frames!r}"
    route_frame = route_decided_frames[0]
    assert route_frame["route"] == "nextseek_query"
    assert route_frame.get("model_class") is None

    assert any(f.get("type") == "error" for f in frames), (
        f"expected empty-query error frame; frames={frames!r}"
    )
    assert any(f.get("type") == "session_ended" for f in frames), (
        f"expected session_ended after error; frames={frames!r}"
    )

    await asyncio.sleep(1.5)

    after_containers = _running_image_container_ids()
    leaked = after_containers - before_containers
    assert not leaked, f"router-on path left running container(s): {sorted(leaked)!r}"
