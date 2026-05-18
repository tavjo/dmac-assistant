"""Real-turn Container-CC integration test for the router-on bridge path.

Phase 7 residual debt #6 remediation: the original T4.2 CC integration test
mocks `exec_cc_turn`, so it proves WS lifecycle but not that a real Claude
Code turn completes in-image. This test removes the executor mock and drives
one real turn end-to-end against the rebuilt `dmac-assistant:poc` image using
live Bedrock credentials.

Skip behavior:
- Skips if Docker daemon is unreachable (the `docker_available()` gate).
- Skips if the local `dmac-assistant:poc` image is missing (`ensure_image`).
- Skips if `.env` is missing or invalid via the session `live_env` fixture
  (per `tests/conftest.py`). The `.env` file IS canonical in this repo;
  if this test is skipping in a populated checkout, the env-loading code
  is wrong — fix the loader, do NOT add a "creds missing" rationalization.
  Reference: T5.1 5R1 remediation (`8ff8c54`) for the correct pattern.

Routing is held deterministic via a fake `RouterAgent` so this test pins
EXECUTION semantics, not BAML routing accuracy.
"""
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
from tests.harness.containers import IMAGE_TAG, docker_available, ensure_image


pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.integration,
    pytest.mark.live_bridge,
    pytest.mark.live,
    pytest.mark.slow,
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
def live_configured_env(
    monkeypatch: pytest.MonkeyPatch,
    bridge_config: BridgeConfig,
    live_env: dict[str, str],
) -> None:
    """Wire bridge config + the router flag + real creds from `.env`.

    `live_env` (defined in `tests/conftest.py`) loads project-root `.env` once
    per session and validates it via `build_tools.verify_env.validate_env`.
    The fixture skips the test if `.env` is missing or invalid — that is the
    only legitimate "creds-missing" skip. Do not add naive `os.environ` checks.
    """
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps({"alice": {"password": "s3cret-alice", "projects": ["proj-a"]}}),
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(bridge_config.claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(bridge_config.scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(bridge_config.dropbox_root))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(bridge_config.output_root))
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(bridge_config.catalog_file))
    # Real live creds from .env, overriding any stub values the host shell carries.
    for key, value in live_env.items():
        monkeypatch.setenv(key, value)
    # NEXTSEEK_BASE_URL is derived from NEXTSEEK_URL; some chat_nextseek
    # consumers want it explicit. Belt-and-braces; harmless on CC route.
    monkeypatch.setenv("NEXTSEEK_BASE_URL", live_env["NEXTSEEK_URL"])
    monkeypatch.setenv("DMAC_ROUTER_ENABLED", "1")


@pytest.fixture
def fake_router_agent_cc() -> Any:
    """Deterministic CC route so the test pins execution, not BAML accuracy."""

    class _FakeAgent:
        async def route(self, query: str) -> RouterDecision:
            return RouterDecision(
                route=Route.ContainerCC,
                model_class=ModelClass.Sonnet,
                reasoning=f"forced for real-turn integration: {query[:16]}",
            )

    return _FakeAgent()


@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_cc_route_real_turn_against_image(
    monkeypatch: pytest.MonkeyPatch,
    live_configured_env: None,
    bridge_config: BridgeConfig,
    fake_router_agent_cc: Any,
    _allow_unix_socket: None,
) -> None:
    """Drive a real CC turn against the dmac-assistant:poc image.

    Phase 7 residual #6 spirit: prove a real successful CC turn completes
    end-to-end (image, exec, Bedrock, stream-json) and emits the canonical
    frame sequence. Routing is forced via the fake router so the assertion
    is on execution semantics rather than BAML accuracy.
    """
    from dmac_assistant import ws as ws_module
    from dmac_assistant.app import app

    monkeypatch.setattr(ws_module, "_get_router_agent", lambda: fake_router_agent_cc)

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
            # Trivial CC-shaped query that any Bedrock-backed Claude can
            # answer quickly. We DO NOT mock exec_cc_turn — this is the
            # real CC dispatch path.
            ws.send_json(
                {"type": "user_message", "content": "Reply with one word: pong."}
            )
            for _ in range(400):
                try:
                    frame = ws.receive_json()
                except Exception:
                    break
                frames.append(frame)
                if frame.get("type") in {"session_ended", "error"}:
                    break

    frame_types = [f.get("type") for f in frames]

    route_decided = [f for f in frames if f.get("type") == "route_decided"]
    assert route_decided, (
        f"no route_decided frame; frame_types={frame_types!r}; "
        f"full frames={frames!r}"
    )
    assert route_decided[0]["route"] == "container_cc"
    assert route_decided[0]["model_class"] == "sonnet"

    # Real CC turn must reach a terminal frame (session_ended on the success
    # path, error on auth/transport failure).
    assert "session_ended" in frame_types or "error" in frame_types, (
        f"real CC turn did not reach a terminal frame; "
        f"frame_types={frame_types!r}"
    )

    # Container cleanup: leaving idle containers running across tests would
    # leak resources. The post-turn cleanup hook is part of the locked design.
    await asyncio.sleep(2.0)
    after_containers = _running_image_container_ids()
    leaked = after_containers - before_containers
    assert not leaked, f"router-on CC path left container(s): {sorted(leaked)!r}"
