"""Part C: hermetic integration test for _chat_ws_router_on → sidecar-publish closure.

Drives the REAL `_chat_ws_router_on` via TestClient with:
  - Stubbed router agent (deterministic ContainerCC decision, no BAML/LLM)
  - Stubbed container/attach (_FakeAttach from the post_turn template)
  - A SYNTHETIC artifact pre-staged in a tmp sidecar staging dir

Asserts:
  1. `sweep_sidecar_staging` was invoked BY the closure (provenance wrap)
  2. The sweep was called with the real `config.sidecar_staging_root`
  3. A file is published to `<output>/<user_id>/…` whose sha256 matches the staged bytes

Does NOT require a live stack. Runs in the default hermetic suite.
Marks: no 'live', no 'live_bridge', no 'live_docker'.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dmac_assistant.router.baml_client.types import ModelClass, Route, RouterDecision
from dmac_assistant.staging_sweep import sweep_sidecar_staging as _real_sweep


# ---------------------------------------------------------------------------
# Shared fake-attach infrastructure (mirrors test_chat_ws_post_turn.py)
# ---------------------------------------------------------------------------

class _FakeAttach:
    """Sync attach-socket double that emits system/init + result frames."""

    def __init__(self, frames: list[tuple[str, bytes]]) -> None:
        self._frames = list(frames)

    def read_frame(self) -> tuple[str, bytes] | None:
        if not self._frames:
            return None
        return self._frames.pop(0)

    def send_stdin(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        pass


def _make_fake_attach() -> _FakeAttach:
    """Return a _FakeAttach emitting system/init + result (normal turn end)."""
    return _FakeAttach([
        ("stdout", b'{"type":"system","subtype":"init","session_id":"sid-t18"}\n'),
        ("stdout", b'{"type":"result"}\n'),
    ])


# ---------------------------------------------------------------------------
# _allow_unix_socket fixture (same pattern as test_chat_ws_post_turn.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def _allow_unix_socket():
    """Re-enable AF_UNIX sockets for Starlette TestClient WS loop."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _user_hash(api_user: str) -> str:
    """Must match staging_sweep.sweep_sidecar_staging (sha256 of user bytes)."""
    return hashlib.sha256(api_user.encode("utf-8")).hexdigest()


def _stage_synthetic_artifact(
    staging_root: Path,
    user_id: str,
    request_id: str,
    filename: str,
    content: bytes,
) -> Path:
    """Pre-stage a synthetic artifact under staging_root/<user_hash>/<request_id>/.

    Writes the artifact file then the .complete marker, exactly as the sidecar
    does on a real report op.

    Returns the path of the staged artifact file.
    """
    user_hash = _user_hash(user_id)
    req_dir = staging_root / user_hash / request_id
    req_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = req_dir / filename
    artifact_path.write_bytes(content)
    # Write .complete marker (sweep_sidecar_staging requires this)
    (staging_root / user_hash / f"{request_id}.complete").write_bytes(b"")
    return artifact_path


def _find_published(output_user_dir: Path) -> list[Path]:
    """Return all files under <output_user_dir>/…, recursively."""
    if not output_user_dir.exists():
        return []
    return [p for p in sorted(output_user_dir.rglob("*")) if p.is_file()]


# ---------------------------------------------------------------------------
# The hermetic test
# ---------------------------------------------------------------------------

@pytest.mark.timeout(10)
def test_router_on_sidecar_publish_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _allow_unix_socket: None,
) -> None:
    """_chat_ws_router_on closure sweeps a pre-staged sidecar artifact to output.

    Anti-gaming invariants verified:
    - `sweep_sidecar_staging` is called BY the closure (via `fire_post_turn_copy`),
      not out-of-band by the test.
    - The call is made with the real config.sidecar_staging_root (not a different dir).
    - The published file's sha256 matches the staged artifact bytes.
    """
    user_id = "testuser"
    scratch_root = tmp_path / "scratch"
    output_root = tmp_path / "output"
    claude_users = tmp_path / "claude-users"
    dropbox = tmp_path / "dropbox"
    staging_root = tmp_path / "sidecar-staging"

    # Create required dirs
    (scratch_root / user_id).mkdir(parents=True)
    output_root.mkdir()
    claude_users.mkdir()
    dropbox.mkdir()
    staging_root.mkdir()

    # Pre-stage a SYNTHETIC artifact (known bytes).
    synthetic_bytes = b"T18-hermetic-test-artifact-" + uuid.uuid4().hex.encode()
    request_id = "req-" + uuid.uuid4().hex[:12]
    staged_path = _stage_synthetic_artifact(
        staging_root=staging_root,
        user_id=user_id,
        request_id=request_id,
        filename="report.txt",
        content=synthetic_bytes,
    )
    expected_sha256 = _sha256(synthetic_bytes)

    # ── Provenance instrumentation ──────────────────────────────────────────
    # Wrap `dmac_assistant.ws._sweep_then_diff` (the function the closure calls)
    # to record invocation and delegate to the REAL implementation.
    # This proves the CLOSURE called it — not the test itself.
    sweep_calls: list[dict[str, Any]] = []

    import dmac_assistant.ws as ws_module

    _real_sweep_then_diff = ws_module._sweep_then_diff

    def _recording_sweep_then_diff(config: Any, identity: Any, pre_turn_files: Any) -> Any:
        sweep_calls.append({
            "sidecar_staging_root": getattr(config, "sidecar_staging_root", None),
            "user_id": identity.user_id,
        })
        return _real_sweep_then_diff(config, identity, pre_turn_files)

    monkeypatch.setattr("dmac_assistant.ws._sweep_then_diff", _recording_sweep_then_diff)

    # ── Stub infra (legitimate — NOT what's being tested) ──────────────────

    # Stub container start/stop (infra we're not testing).
    monkeypatch.setattr(
        "dmac_assistant.ws.async_start_container",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr("dmac_assistant.ws.async_stop_and_remove", AsyncMock())

    # For the router-on (ContainerCC) path, `_dispatch_cc_turn` calls
    # `exec_cc_turn` (a sync function in containers.py), NOT `async_attach`.
    # `exec_cc_turn` returns a BridgeAttachSocket; stub it to return a fake
    # attach that emits system/init + result so the turn ends cleanly.
    fake_attach_instance = _make_fake_attach()

    def _fake_exec_cc_turn(*args: Any, **kwargs: Any) -> Any:
        return fake_attach_instance

    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", _fake_exec_cc_turn)

    # Stub the router agent to return ContainerCC deterministically (no BAML/LLM).
    class _FakeRouter:
        async def route(self, query: str) -> RouterDecision:
            return RouterDecision(
                route=Route.ContainerCC,
                model_class=ModelClass.Sonnet,
                reasoning="hermetic T18 stub",
            )

    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: _FakeRouter())

    # Enable the router path and point config at our tmp dirs.
    monkeypatch.setenv("DMAC_ROUTER_ENABLED", "1")
    monkeypatch.setenv("DMAC_DEV_MODE", "1")
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps({user_id: {"password": "pw", "projects": ["proj-a"]}}),
    )
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(scratch_root))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(claude_users))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(dropbox))
    # Point the sidecar staging root at our pre-staged dir (key: the closure
    # reads this from config.sidecar_staging_root via load_config()).
    monkeypatch.setenv("DMAC_SIDECAR_STAGING_ROOT", str(staging_root))
    # Empty network → falsy → no Docker network check (containers.py:440-455).
    monkeypatch.setenv("DMAC_SIDECAR_NETWORK", "")

    # ── Wire auth (same pattern as test_chat_ws_post_turn.py) ──────────────
    from dmac_assistant.app import app
    from dmac_assistant.auth import AuthenticatedIdentity, get_token_store

    class _StubTokenStore:
        def verify(self, token: str) -> AuthenticatedIdentity:
            assert token == "t18-token"
            return AuthenticatedIdentity(
                user_id=user_id,
                password=SecretStr("pw"),
                projects=["proj-a"],
            )

    app.dependency_overrides[get_token_store] = lambda: _StubTokenStore()
    try:
        # ── Drive the REAL _chat_ws_router_on via TestClient ───────────────
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/chat", subprotocols=["dmac.bearer", "t18-token"]
            ) as ws:
                ws.send_json({"type": "user_message", "content": "report please"})
                while True:
                    frame = ws.receive_json()
                    if frame.get("type") == "session_ended":
                        break
    finally:
        app.dependency_overrides.pop(get_token_store, None)

    # ── Assertions ──────────────────────────────────────────────────────────

    # 1. PROVENANCE: sweep_then_diff was called BY the closure (not out-of-band).
    assert len(sweep_calls) >= 1, (
        "sweep_then_diff was never called — the _chat_ws_router_on post_turn_callback "
        "did not fire. The closure was not exercised."
    )

    # 2. The call was made with the real config.sidecar_staging_root pointing at
    #    our staging_root (not some other directory).
    assert sweep_calls[0]["sidecar_staging_root"] == staging_root, (
        f"_sweep_then_diff was called with staging_root="
        f"{sweep_calls[0]['sidecar_staging_root']!r} but expected {staging_root!r}. "
        "The closure is not using the real config.sidecar_staging_root."
    )

    # 3. The correct user_id was passed (so _user_hash matches the staged dir).
    assert sweep_calls[0]["user_id"] == user_id, (
        f"_sweep_then_diff was called with user_id={sweep_calls[0]['user_id']!r} "
        f"but expected {user_id!r}. The closure identity is wrong."
    )

    # 4. An artifact was published to output_root/<user_id>/…
    published = _find_published(output_root / user_id)
    assert published, (
        f"No files published to {output_root / user_id} after the WS turn. "
        "The closure's post-turn copy did not publish the staged artifact."
    )

    # 5. The published artifact's bytes sha256-match the staged synthetic bytes.
    # The sweep copies to nextseek-artifacts/<request_id>/report.txt under scratch,
    # then dispatch_post_turn_copy copies to output. Find the file by its name
    # (which the sweep preserves) under the output tree.
    matched: list[Path] = []
    for pub_file in published:
        if _sha256(pub_file.read_bytes()) == expected_sha256:
            matched.append(pub_file)

    assert matched, (
        f"sha256 MISMATCH: none of {[p.name for p in published]} matched "
        f"expected sha256={expected_sha256}. "
        "The published artifact bytes differ from the staged artifact — "
        "either a different artifact was published or the bytes were corrupted."
    )
