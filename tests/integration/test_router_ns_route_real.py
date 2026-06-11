"""Real-turn NextSEEK-Query integration test for the router-on bridge path.

Phase 7 residual debt #6 remediation: the original T4.2 NS integration test
only exercises the empty-query error path, so it proves WS lifecycle but not
that a real chat_nextseek run completes in-image. This test sends a
non-empty NS-shaped query and asserts the runner drives the turn through
to a real terminal event (success or chat_nextseek-emitted error) plus the
canonical session_ended frame.

Notes on assertions:
- The test does NOT assert on assistant-message *content* — that is Phase 7
  residual #1 (NS happy-path quality), which is OUT OF SCOPE for this
  remediation. The goal here is to prove the bridge<->runner<->chat_nextseek
  pipeline completes a real turn, not that any specific NS answer is correct.
- A "successful turn" means either an `assistant_message` plus
  `session_ended`, OR an `error` frame followed by `session_ended` — both
  are valid runner-side terminal outcomes. The lifecycle invariant is that
  `session_ended` fires regardless of NS answer quality.

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
    monkeypatch.setenv("NEXTSEEK_BASE_URL", live_env["NEXTSEEK_URL"])
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

    Phase 7 residual #6 spirit: prove the bridge<->runner_ns.py<->chat_nextseek
    pipeline completes a real turn end-to-end and emits `session_ended`
    regardless of NS answer quality (#1 is out of scope here).
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

    # Lifecycle invariant: NS turn must reach session_ended. The chat_nextseek
    # answer may be "unsupported operation" (Phase 7 #1, out of scope) — the
    # bridge still must close the turn cleanly.
    assert "session_ended" in frame_types, (
        f"real NS turn did not reach session_ended; "
        f"frame_types={frame_types!r}"
    )

    # Must have either an assistant_message (chat_nextseek answered) or an
    # error frame (chat_nextseek failed cleanly). Both are valid terminals.
    assert any(t in {"assistant_message", "error"} for t in frame_types), (
        f"real NS turn produced neither assistant_message nor error before "
        f"session_ended; frame_types={frame_types!r}"
    )

    await asyncio.sleep(2.0)
    after_containers = _running_image_container_ids()
    leaked = after_containers - before_containers
    assert not leaked, f"router-on NS path left container(s): {sorted(leaked)!r}"
