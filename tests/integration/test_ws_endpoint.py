"""T06 behavioral contract for the ``/ws/chat`` WebSocket endpoint.

These tests mock T05's docker-py surface (``async_start_container``,
``async_attach``, ``async_stop_and_remove``) so the bridge behavior can be
exercised without a real Docker daemon. Live Docker belongs to T07.

The parser-handling fakes below drive the attach wrapper's ``read_frame``
contract: each frame is a ``("stdout", bytes)`` tuple terminating on ``None``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from dmac_assistant.auth import (
    AuthenticatedIdentity,
    TokenStore,
    get_token_store,
    router as auth_router,
)
from dmac_assistant.config import BridgeConfig, UserRecord
from tests.harness.canaries import (
    ALL_CANARIES,
    CANARY_SECRET,
    scan_for_canaries,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def allow_unix_socket_only():
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
    return BridgeConfig(
        users={"alice": UserRecord(password="s3cret-alice", projects=["proj-a"])},
        claude_users_root=tmp_path / "claude-users",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        bridge_host="127.0.0.1",
        bridge_port=8000,
    )


@pytest.fixture
def configured_env(
    monkeypatch: pytest.MonkeyPatch, bridge_config: BridgeConfig
) -> None:
    """Publish the bridge config into the env so ``load_config()`` succeeds."""
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps(
            {
                "alice": {
                    "password": "s3cret-alice",
                    "projects": ["proj-a"],
                }
            }
        ),
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(bridge_config.claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(bridge_config.scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(bridge_config.dropbox_root))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # NB: intentionally do NOT set AWS_BEARER_TOKEN_BEDROCK on the host env.
    # Canary scan covers that secret via CANARY_SECRET.


@pytest.fixture
def token_store(bridge_config: BridgeConfig) -> TokenStore:
    store = TokenStore()
    store.issue(
        user_id="alice", password="s3cret-alice", config=bridge_config
    )
    return store


def _issued_token(store: TokenStore) -> str:
    # TokenStore exposes _tokens; grab the one we just issued for tests.
    return next(iter(store._tokens.keys()))  # noqa: SLF001 — test-only access


# ---------------------------------------------------------------------------
# Fakes for T05 + Claude stream-json
# ---------------------------------------------------------------------------


class _FakeAttachSocket:
    """Test double for ``BridgeAttachSocket``.

    ``frames`` is a list of ``("stdout"|"stderr", bytes) | None`` items; a
    ``None`` marks EOF. Each call to ``read_frame`` consumes one entry.
    """

    def __init__(self, frames: list[tuple[str, bytes] | None]) -> None:
        self.frames = list(frames)
        self.stdin_writes: list[bytes] = []
        self.closed = False
        self.stdin_closed = False

    def read_frame(self) -> tuple[str, bytes] | None:
        if not self.frames:
            return None
        return self.frames.pop(0)

    def send_stdin(self, data: bytes) -> None:
        self.stdin_writes.append(data)

    def close_stdin(self) -> None:
        self.stdin_closed = True

    def close(self) -> None:
        self.closed = True


class _FakeContainer:
    def __init__(self, container_id: str = "cid-123") -> None:
        self.id = container_id


def _init_event(session_id: str) -> bytes:
    return (
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": session_id,
                "model": "claude-sonnet-4-6",
                "cwd": "/home/user",
                "tools": [],
            }
        )
        + "\n"
    ).encode()


def _assistant_text_event(text: str) -> bytes:
    return (
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": text}]},
            }
        )
        + "\n"
    ).encode()


def _assistant_tool_use_event(
    tool_id: str, name: str, tool_input: dict[str, Any]
) -> bytes:
    return (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": name,
                            "input": tool_input,
                        }
                    ]
                },
            }
        )
        + "\n"
    ).encode()


def _result_event() -> bytes:
    return (json.dumps({"type": "result", "subtype": "success"}) + "\n").encode()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_store: TokenStore,
    frames: list[tuple[str, bytes] | None],
    start_hook: Callable[..., Any] | None = None,
    start_raises: BaseException | None = None,
) -> tuple[FastAPI, dict[str, Any]]:
    """Build a FastAPI app with the WS router wired + T05 fakes installed."""
    from dmac_assistant import ws as ws_module

    state: dict[str, Any] = {
        "fake_socket": _FakeAttachSocket(frames),
        "fake_container": _FakeContainer(),
        "start_calls": [],
        "stop_calls": [],
        "attach_calls": [],
    }

    async def _fake_start(
        identity: AuthenticatedIdentity,
        *,
        image: str,
        session_id: str | None,
        bridge_env,
        config,
    ):
        state["start_calls"].append(
            {
                "user_id": identity.user_id,
                "image": image,
                "session_id": session_id,
                "bridge_env_keys": sorted(bridge_env.keys()),
            }
        )
        if start_hook is not None:
            await start_hook()
        if start_raises is not None:
            raise start_raises
        return state["fake_container"]

    async def _fake_attach(container):
        state["attach_calls"].append(container)
        return state["fake_socket"]

    async def _fake_stop(container, *, timeout: int = 5):
        state["stop_calls"].append(container)

    monkeypatch.setattr(ws_module, "async_start_container", _fake_start)
    monkeypatch.setattr(ws_module, "async_attach", _fake_attach)
    monkeypatch.setattr(ws_module, "async_stop_and_remove", _fake_stop)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(ws_module.router, prefix="/ws", tags=["ws"])
    app.dependency_overrides[get_token_store] = lambda: token_store
    return app, state


# ---------------------------------------------------------------------------
# Unit tests for the pure helper
# ---------------------------------------------------------------------------


def test_assistant_text_blocks_map_to_assistant_message_frames() -> None:
    from dmac_assistant.streamjson import StreamEvent
    from dmac_assistant.ws import stream_event_to_ws_frames

    event = StreamEvent(
        kind="event",
        payload={
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        },
    )

    frames = stream_event_to_ws_frames(event, current_session_id="sess-1")

    assert frames == [{"type": "assistant_message", "content": "hello"}]


def test_tool_use_blocks_map_to_tool_use_frames() -> None:
    from dmac_assistant.streamjson import StreamEvent
    from dmac_assistant.ws import stream_event_to_ws_frames

    event = StreamEvent(
        kind="event",
        payload={
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "Bash",
                        "input": {"cmd": "ls"},
                    }
                ]
            },
        },
    )

    frames = stream_event_to_ws_frames(event, current_session_id="sess-1")

    assert frames == [
        {"type": "tool_use", "tool": "Bash", "input": {"cmd": "ls"}, "id": "tu-1"}
    ]


def test_parser_error_becomes_stream_json_error_frame() -> None:
    from dmac_assistant.streamjson import StreamEvent, StreamJsonErrorDetail
    from dmac_assistant.ws import stream_event_to_ws_frames

    event = StreamEvent(
        kind="error",
        error=StreamJsonErrorDetail(line=b"oops", reason="bad json"),
    )

    frames = stream_event_to_ws_frames(event, current_session_id=None)

    assert frames == [
        {"type": "error", "reason": "stream_json_error", "detail": "bad json"}
    ]


def test_result_event_emits_session_ended() -> None:
    from dmac_assistant.streamjson import StreamEvent
    from dmac_assistant.ws import stream_event_to_ws_frames

    event = StreamEvent(kind="event", payload={"type": "result", "subtype": "success"})

    frames = stream_event_to_ws_frames(event, current_session_id="sess-9")

    assert frames == [{"type": "session_ended", "session_id": "sess-9"}]


# ---------------------------------------------------------------------------
# WS endpoint behavioral tests
# ---------------------------------------------------------------------------


def test_missing_authorization_header_closes_4401(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=[None])
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/chat"):
                pass
    assert exc.value.code == 4401


def test_invalid_bearer_token_closes_4401(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=[None])
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/chat", headers={"Authorization": "Bearer wrong-token"}
            ):
                pass
    assert exc.value.code == 4401


def test_first_frame_must_be_user_message(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    app, state = _make_app(monkeypatch, token_store=token_store, frames=[None])
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "not_a_message", "content": "x"})
            frame = ws.receive_json()
            assert frame == {"type": "error", "reason": "bad_handshake"}
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
    assert exc.value.code == 4400
    # bad handshake means we never started a container
    assert state["start_calls"] == []


def test_first_frame_new_session_true_skips_resume_lookup(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    bridge_config: BridgeConfig,
    token_store: TokenStore,
) -> None:
    # Create an existing session file that WOULD be picked up if resume ran.
    target = (
        bridge_config.claude_users_root
        / "alice"
        / ".claude"
        / "projects"
        / "-home-user"
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / "11111111-1111-1111-1111-111111111111.jsonl").write_text("{}\n")

    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("new-session-id")),
        ("stdout", _result_event()),
        None,
    ]
    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "hi", "new_session": True}
            )
            assert ws.receive_json() == {
                "type": "session_started",
                "session_id": "new-session-id",
            }
            assert ws.receive_json() == {
                "type": "session_ended",
                "session_id": "new-session-id",
            }
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    assert state["start_calls"][0]["session_id"] is None


def test_first_frame_without_new_session_uses_most_recent_session(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    bridge_config: BridgeConfig,
    token_store: TokenStore,
) -> None:
    target = (
        bridge_config.claude_users_root
        / "alice"
        / ".claude"
        / "projects"
        / "-home-user"
    )
    target.mkdir(parents=True, exist_ok=True)
    existing_id = "22222222-2222-2222-2222-222222222222"
    (target / f"{existing_id}.jsonl").write_text("{}\n")

    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event(existing_id)),
        ("stdout", _result_event()),
        None,
    ]
    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi"})
            assert ws.receive_json() == {
                "type": "session_started",
                "session_id": existing_id,
            }
            # drain
            while True:
                try:
                    ws.receive_json()
                except WebSocketDisconnect:
                    break

    assert state["start_calls"][0]["session_id"] == existing_id


def test_resume_mismatch_emits_resume_failed_then_session_started(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    bridge_config: BridgeConfig,
    token_store: TokenStore,
) -> None:
    target = (
        bridge_config.claude_users_root
        / "alice"
        / ".claude"
        / "projects"
        / "-home-user"
    )
    target.mkdir(parents=True, exist_ok=True)
    requested_id = "33333333-3333-3333-3333-333333333333"
    (target / f"{requested_id}.jsonl").write_text("{}\n")

    actual_id = "44444444-4444-4444-4444-444444444444"
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event(actual_id)),
        ("stdout", _result_event()),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi"})
            first = ws.receive_json()
            second = ws.receive_json()
            # Ordering: error first, session_started second (DD-14).
            assert first == {
                "type": "error",
                "reason": "resume_failed",
                "requested": requested_id,
                "actual": actual_id,
            }
            assert second == {
                "type": "session_started",
                "session_id": actual_id,
            }
            while True:
                try:
                    ws.receive_json()
                except WebSocketDisconnect:
                    break


def test_session_started_precedes_assistant_frames(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("sess-1") + _assistant_text_event("hi there")),
        ("stdout", _result_event()),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)

    received: list[dict[str, Any]] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            while True:
                try:
                    received.append(ws.receive_json())
                except WebSocketDisconnect:
                    break

    types_in_order = [f["type"] for f in received]
    assert types_in_order[0] == "session_started"
    assert "assistant_message" in types_in_order
    assert types_in_order.index("session_started") < types_in_order.index(
        "assistant_message"
    )


def test_disconnect_path_closes_socket_and_stops_container(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    # After the init, emit a synthetic result event and EOF so the server
    # read loop completes deterministically; the cleanup path must fire
    # regardless of whether the client or the container stream ended first.
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("sess-1")),
        ("stdout", _result_event()),
        None,
    ]

    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            # Drain until the server closes.
            while True:
                try:
                    ws.receive_json()
                except WebSocketDisconnect:
                    break

    # Outer TestClient exit awaits ASGI shutdown, giving the ws endpoint's
    # try/finally room to finish. At that point cleanup must be observable.
    _wait_until(lambda: bool(state["stop_calls"]))
    assert state["stop_calls"], "container must be stopped on disconnect"
    assert state["fake_socket"].closed, "attach socket must be closed on disconnect"


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll ``predicate`` until it holds or ``timeout`` elapses."""
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return
        _time.sleep(0.01)


def test_cancellation_during_startup_still_stops_container(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """Container-start failure path: spec §3 — close 1011 + cleanup."""

    class _BoomError(RuntimeError):
        pass

    app, state = _make_app(
        monkeypatch,
        token_store=token_store,
        frames=[None],
        start_raises=_BoomError("boom"),
    )
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/chat", headers={"Authorization": f"Bearer {token}"}
            ) as ws:
                ws.send_json(
                    {"type": "user_message", "content": "hi", "new_session": True}
                )
                # The bridge should emit container_start_failed then close 1011.
                frame = ws.receive_json()
                assert frame == {
                    "type": "error",
                    "reason": "container_start_failed",
                }
                ws.receive_json()
    assert exc.value.code == 1011
    # start raised, so attach never happened — no socket to close, no container to stop.
    assert state["stop_calls"] == []


def test_stream_event_to_ws_frames_ignores_non_dict_blocks_and_unknown_types() -> None:
    from dmac_assistant.streamjson import StreamEvent
    from dmac_assistant.ws import stream_event_to_ws_frames

    # non-dict block is skipped; non-assistant/non-result returns []
    event = StreamEvent(
        kind="event",
        payload={
            "type": "assistant",
            "message": {
                "content": [
                    "not-a-dict",
                    {"type": "text"},  # missing text value -> skipped
                    {"type": "text", "text": "ok"},
                ]
            },
        },
    )
    assert stream_event_to_ws_frames(event, current_session_id=None) == [
        {"type": "assistant_message", "content": "ok"}
    ]

    other = StreamEvent(kind="event", payload={"type": "system", "subtype": "other"})
    assert stream_event_to_ws_frames(other, current_session_id=None) == []

    # tool_use with non-dict input coerces to {}
    tool_event = StreamEvent(
        kind="event",
        payload={
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "x", "name": "Bash", "input": "raw"}
                ]
            },
        },
    )
    assert stream_event_to_ws_frames(tool_event, current_session_id=None) == [
        {"type": "tool_use", "tool": "Bash", "input": {}, "id": "x"}
    ]


def test_invalid_bearer_scheme_closes_4401(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=[None])
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/chat", headers={"Authorization": "Basic abc"}
            ):
                pass
    assert exc.value.code == 4401


def test_first_frame_non_dict_is_bad_handshake(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    app, state = _make_app(monkeypatch, token_store=token_store, frames=[None])
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json(["not", "a", "dict"])
            assert ws.receive_json() == {"type": "error", "reason": "bad_handshake"}
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
    assert exc.value.code == 4400
    assert state["start_calls"] == []


def test_stderr_frames_from_container_are_dropped(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    frames: list[tuple[str, bytes] | None] = [
        ("stderr", b"diagnostic noise\n"),
        ("stdout", _init_event("sess-X")),
        ("stderr", b"more noise\n"),
        ("stdout", _assistant_text_event("hi")),
        ("stdout", _result_event()),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    received: list[dict[str, Any]] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            while True:
                try:
                    received.append(ws.receive_json())
                except WebSocketDisconnect:
                    break

    types_seen = [f["type"] for f in received]
    # no "error" for stderr, and the ordered sequence is maintained.
    assert types_seen == ["session_started", "assistant_message", "session_ended"]


def test_attach_failure_after_successful_start_closes_1011_and_stops_container(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    from dmac_assistant import ws as ws_module

    app, state = _make_app(
        monkeypatch, token_store=token_store, frames=[None]
    )

    async def _boom_attach(container):
        raise RuntimeError("attach broken")

    monkeypatch.setattr(ws_module, "async_attach", _boom_attach)
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/chat", headers={"Authorization": f"Bearer {token}"}
            ) as ws:
                ws.send_json(
                    {"type": "user_message", "content": "hi", "new_session": True}
                )
                frame = ws.receive_json()
                assert frame == {"type": "error", "reason": "container_start_failed"}
                ws.receive_json()
    assert exc.value.code == 1011
    # container was started successfully, so it must be cleaned up
    _wait_until(lambda: bool(state["stop_calls"]))
    assert state["stop_calls"]


def test_stdin_write_failure_on_first_frame_is_swallowed(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """If send_stdin raises, the bridge keeps running the read loop."""
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("sess-Y")),
        ("stdout", _result_event()),
        None,
    ]
    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)

    def _bad_send_stdin(data: bytes) -> None:
        raise OSError("pipe closed")

    state["fake_socket"].send_stdin = _bad_send_stdin  # type: ignore[assignment]
    token = _issued_token(token_store)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            assert ws.receive_json()["type"] == "session_started"
            assert ws.receive_json()["type"] == "session_ended"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_trailing_partial_line_surfaces_as_stream_json_error(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """A non-newline-terminated trailing line must flush as a parser error."""
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("sess-T")),
        # trailing partial (no newline) — parser.flush() surfaces an error.
        ("stdout", b'{"type":"assistant",'),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    received: list[dict[str, Any]] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            while True:
                try:
                    received.append(ws.receive_json())
                except WebSocketDisconnect:
                    break

    types_seen = [f["type"] for f in received]
    assert "error" in types_seen
    err = next(f for f in received if f["type"] == "error")
    assert err["reason"] == "stream_json_error"
    # synthetic session_ended still emitted for the started session.
    assert types_seen[-1] == "session_ended"


def test_clean_eof_without_result_emits_synthetic_session_ended(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """If the stream ends without an explicit result event, emit one anyway."""
    frames: list[tuple[str, bytes] | None] = [
        ("stdout", _init_event("sess-Z")),
        ("stdout", _assistant_text_event("partial")),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    received: list[dict[str, Any]] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "hi", "new_session": True})
            while True:
                try:
                    received.append(ws.receive_json())
                except WebSocketDisconnect:
                    break
    types_seen = [f["type"] for f in received]
    assert types_seen == ["session_started", "assistant_message", "session_ended"]
    assert received[-1] == {"type": "session_ended", "session_id": "sess-Z"}


def test_subsequent_user_messages_are_forwarded_to_stdin(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """Later frames (after the first) get relayed to container stdin."""
    import threading
    import time

    # Use a gated fake so the server doesn't EOF before the client sends.
    release = threading.Event()

    class _GatedSocket(_FakeAttachSocket):
        def __init__(self, queue: list[tuple[str, bytes] | None]) -> None:
            super().__init__(queue)

        def read_frame(self) -> tuple[str, bytes] | None:
            if self.frames:
                return self.frames.pop(0)
            # Wait for the test to permit EOF.
            release.wait(timeout=2.0)
            return None

    gated = _GatedSocket(
        [
            ("stdout", _init_event("sess-G")),
        ]
    )

    from dmac_assistant import ws as ws_module

    container = _FakeContainer()
    start_calls: list[Any] = []
    stop_calls: list[Any] = []

    async def _fake_start(identity, *, image, session_id, bridge_env, config):
        start_calls.append(identity.user_id)
        return container

    async def _fake_attach(c):
        return gated

    async def _fake_stop(c, *, timeout: int = 5):
        stop_calls.append(c)

    monkeypatch.setattr(ws_module, "async_start_container", _fake_start)
    monkeypatch.setattr(ws_module, "async_attach", _fake_attach)
    monkeypatch.setattr(ws_module, "async_stop_and_remove", _fake_stop)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(ws_module.router, prefix="/ws", tags=["ws"])
    app.dependency_overrides[get_token_store] = lambda: token_store

    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_json({"type": "user_message", "content": "first", "new_session": True})
            assert ws.receive_json()["type"] == "session_started"

            # Relay frames: one valid user_message, then malformed shapes
            # that should be ignored.
            ws.send_json({"type": "user_message", "content": "second"})
            ws.send_json({"type": "ignored"})
            ws.send_json({"type": "user_message", "content": 123})
            ws.send_json("not-a-dict")
            # Give the relay task a moment to pick them up.
            for _ in range(40):
                if any(b"second" in w for w in gated.stdin_writes):
                    break
                time.sleep(0.01)

            release.set()
            while True:
                try:
                    ws.receive_json()
                except WebSocketDisconnect:
                    break

    writes = b"".join(gated.stdin_writes)
    assert b"first\n" in writes
    assert b"second\n" in writes


def test_internal_exception_during_run_emits_internal_error_frame(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """If the read loop blows up unexpectedly, emit ``error:internal`` + close 1011."""
    from dmac_assistant import ws as ws_module

    class _Boom(RuntimeError):
        pass

    class _BoomSocket(_FakeAttachSocket):
        def read_frame(self) -> tuple[str, bytes] | None:
            raise _Boom("reader exploded")

    container = _FakeContainer()
    sock = _BoomSocket([])
    stop_calls: list[Any] = []

    async def _fake_start(identity, *, image, session_id, bridge_env, config):
        return container

    async def _fake_attach(c):
        return sock

    async def _fake_stop(c, *, timeout: int = 5):
        stop_calls.append(c)

    monkeypatch.setattr(ws_module, "async_start_container", _fake_start)
    monkeypatch.setattr(ws_module, "async_attach", _fake_attach)
    monkeypatch.setattr(ws_module, "async_stop_and_remove", _fake_stop)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(ws_module.router, prefix="/ws", tags=["ws"])
    app.dependency_overrides[get_token_store] = lambda: token_store

    token = _issued_token(token_store)
    received: list[dict[str, Any]] = []
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/chat", headers={"Authorization": f"Bearer {token}"}
            ) as ws:
                ws.send_json(
                    {"type": "user_message", "content": "hi", "new_session": True}
                )
                while True:
                    received.append(ws.receive_json())

    reasons = [f.get("reason") for f in received if f.get("type") == "error"]
    assert "internal" in reasons
    _wait_until(lambda: bool(stop_calls))
    assert stop_calls


def test_error_frames_and_logs_do_not_contain_canaries(
    allow_unix_socket_only,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    bridge_config: BridgeConfig,
    tmp_path: Path,
) -> None:
    """R-03: AWS bearer / NExtSEEK password / identity must never leak."""
    # Plant canary secrets in host env + user record so any accidental
    # logging of identity/bridge_env surfaces them.
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", CANARY_SECRET)
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps(
            {
                "alice": {
                    "password": ALL_CANARIES[2],  # CANARY_NX_PASS
                    "projects": ["proj-a"],
                }
            }
        ),
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(bridge_config.claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(bridge_config.scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(bridge_config.dropbox_root))

    # Rebuild the token store against the canary-password user record.
    poisoned_config = BridgeConfig(
        users={
            "alice": UserRecord(
                password=ALL_CANARIES[2], projects=["proj-a"]
            )
        },
        claude_users_root=bridge_config.claude_users_root,
        scratch_root=bridge_config.scratch_root,
        dropbox_root=bridge_config.dropbox_root,
        bridge_host="127.0.0.1",
        bridge_port=8000,
    )
    store = TokenStore()
    store.issue(user_id="alice", password=ALL_CANARIES[2], config=poisoned_config)

    class _StartFailure(RuntimeError):
        pass

    app, _state = _make_app(
        monkeypatch,
        token_store=store,
        frames=[None],
        start_raises=_StartFailure("boom"),
    )

    ws_frames_seen: list[dict[str, Any]] = []
    with caplog.at_level(logging.DEBUG, logger="dmac_assistant.ws"):
        with TestClient(app) as client:
            try:
                with client.websocket_connect(
                    "/ws/chat",
                    headers={"Authorization": f"Bearer {_issued_token(store)}"},
                ) as ws:
                    ws.send_json(
                        {"type": "user_message", "content": "hi", "new_session": True}
                    )
                    while True:
                        try:
                            ws_frames_seen.append(ws.receive_json())
                        except WebSocketDisconnect:
                            break
            except WebSocketDisconnect:
                pass

    streams: list[bytes | str] = [json.dumps(f) for f in ws_frames_seen]
    streams.extend(record.getMessage() for record in caplog.records)
    hits = scan_for_canaries(streams, [], ALL_CANARIES + [CANARY_SECRET])
    assert hits == [], f"canary leak detected: {hits}"
