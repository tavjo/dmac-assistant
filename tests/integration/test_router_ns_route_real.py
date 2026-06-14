"""Real-turn NextSEEK-Query integration test for the router-on bridge path.

Originated as Phase 7 residual debt #6: the original T4.2 NS integration test
only exercised the empty-query error path, proving WS lifecycle but not that a
real NS turn completes in-image. This test sends a non-empty NS-shaped query and
drives the turn end-to-end.

T13 (sidecar architecture): the NS route no longer runs chat_nextseek IN the
agent — `runner_ns.py` is a thin client that talks to the NExtSEEK assistant
viewset (and, for granular ops, the shared-cred sidecar over the Docker network).
So this test exercises the bridge<->runner_ns<->assistant-viewset pipeline. It
runs against tavjo's LOCAL NExtSEEK stack (the E2E target); the stack is
data-sparse but every reply is still substantive text.

Notes on assertions (T13 tightening — carry-forward from W3):
- The terminal assertion previously tolerated an `error` frame, so it could pass
  even on a BROKEN NS path. It now REQUIRES a substantive `assistant_message`
  reply (non-empty content) before `session_ended`. An empty-data answer ("no
  samples match") is still substantive text and passes; an error frame fails.
- It does NOT judge answer *correctness* (no semantic verdict here — that is the
  router E2E's BAML judge). "Substantive" = a non-empty assistant reply, not an
  error stub.

Skip behavior matches `tests/integration/test_router_cc_route_real.py`:
docker, image, and `.env` gating only.
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
from dmac_assistant.router.baml_client.types import Route, RouterDecision
from tests.harness.containers import IMAGE_TAG, docker_available, ensure_image
from tests.integration import _sidecar_e2e_helpers as H


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
    """Wire bridge config + the router flag + real creds from `.env`."""
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps({"alice": {"password": "s3cret-alice", "projects": ["proj-a"]}}),
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(bridge_config.claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(bridge_config.scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(bridge_config.dropbox_root))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(bridge_config.output_root))
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(bridge_config.catalog_file))
    for key, value in live_env.items():
        monkeypatch.setenv(key, value)
    # T13: the E2E target is the LOCAL NExtSEEK stack, not the dev server that
    # live_env["NEXTSEEK_URL"] validates to. Point the AGENT container's NS URL at
    # the local stack via the host gateway (the agent is on the sidecar network
    # only; localhost is self-referential in-container). Same constant the T12
    # sidecar suite uses. NEVER edit .env — per-invocation override.
    monkeypatch.setenv("NEXTSEEK_URL", H.AGENT_NEXTSEEK_URL)
    monkeypatch.setenv("NEXTSEEK_BASE_URL", H.AGENT_NEXTSEEK_URL)
    monkeypatch.setenv("DMAC_ROUTER_ENABLED", "1")
    # task-04R1: the post-turn staging sweep DELETES swept request dirs; pin
    # it into the test tmp tree so a live run can never sweep (and delete from)
    # the real default ~/dmac-dev/nextseek-sidecar-staging. DMAC_SIDECAR_NETWORK
    # is deliberately NOT pinned here: live runs exercise production parity and
    # may legitimately attach to the running sidecar stack's network.
    monkeypatch.setenv(
        "DMAC_SIDECAR_STAGING_ROOT", str(bridge_config.scratch_root.parent / "sidecar-staging")
    )


@pytest.fixture
def fake_router_agent_ns() -> Any:
    """Deterministic NS route so the test pins execution, not BAML accuracy."""

    class _FakeAgent:
        async def route(self, query: str) -> RouterDecision:
            return RouterDecision(
                route=Route.NextseekQuery,
                model_class=None,
                reasoning=f"forced for real-turn integration: {query[:16]}",
            )

    return _FakeAgent()


@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_ns_route_real_turn_against_image(
    monkeypatch: pytest.MonkeyPatch,
    live_configured_env: None,
    bridge_config: BridgeConfig,
    fake_router_agent_ns: Any,
    _allow_unix_socket: None,
) -> None:
    """Drive a real NS turn through `runner_ns.py` in-image.

    T13: prove the bridge<->runner_ns.py<->assistant-viewset pipeline completes a
    real turn end-to-end, emits `session_ended`, AND surfaces a substantive
    assistant reply (not an error frame) against the local stack.
    """
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
            # NS-shaped query. The original T5.1 evidence used this exact
            # phrasing under Search-Basic-1; the bridge<->runner<->chat_nextseek
            # round-trip completes regardless of whether chat_nextseek's
            # answer is satisfying.
            ws.send_json(
                {"type": "user_message", "content": "Find me mice treated with NDMA."}
            )
            for _ in range(600):
                try:
                    frame = ws.receive_json()
                except Exception:
                    break
                frames.append(frame)
                if frame.get("type") in {"session_ended"}:
                    break

    frame_types = [f.get("type") for f in frames]

    route_decided = [f for f in frames if f.get("type") == "route_decided"]
    assert route_decided, (
        f"no route_decided frame; frame_types={frame_types!r}; "
        f"full frames={frames!r}"
    )
    assert route_decided[0]["route"] == "nextseek_query"
    assert route_decided[0].get("model_class") is None

    # Lifecycle invariant: NS turn must reach session_ended.
    assert "session_ended" in frame_types, (
        f"real NS turn did not reach session_ended; "
        f"frame_types={frame_types!r}"
    )

    # T13 tightening (W3 carry-forward): require a SUBSTANTIVE assistant reply,
    # not an error frame. The viewset path must produce a real answer against the
    # local stack — a data-sparse "no samples match" reply is still substantive
    # text. An `error` frame (broken NS path) now FAILS this assertion.
    assert "error" not in frame_types, (
        f"real NS turn emitted an error frame (broken NS path); "
        f"frame_types={frame_types!r}"
    )
    assistant_msgs = [f for f in frames if f.get("type") == "assistant_message"]
    assert assistant_msgs, (
        f"real NS turn produced no assistant_message before session_ended; "
        f"frame_types={frame_types!r}"
    )
    reply_text = "".join(str(f.get("content") or "") for f in assistant_msgs).strip()
    assert reply_text, (
        f"real NS turn assistant_message(s) carried no substantive content; "
        f"frames={assistant_msgs!r}"
    )

    await asyncio.sleep(2.0)
    after_containers = _running_image_container_ids()
    leaked = after_containers - before_containers
    assert not leaked, f"router-on NS path left container(s): {sorted(leaked)!r}"
