"""T3.2 ws.py per-turn router dispatch tests."""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord


SECRET = "hunter2-not-a-real-password"
USER_ID = "alice"
MODEL_ID_SONNET = "us.anthropic.claude-sonnet-4-6"
MODEL_ID_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MODEL_ID_OPUS = "us.anthropic.claude-opus-4-8"
NS_SESSION_RE = re.compile(r"^ns-[0-9a-f]{12}$")


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id=USER_ID,
        password=SecretStr(SECRET),
        projects=["proj-a"],
    )


def _config(tmp_path: Path) -> BridgeConfig:
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={
            USER_ID: UserRecord(password=SecretStr(SECRET), projects=["proj-a"]),
        },
        scratch_root=tmp_path / "scratch",
        output_root=tmp_path / "output",
        claude_users_root=tmp_path / "claude",
        dropbox_root=tmp_path / "dropbox",
        catalog_file=catalog,
    )


def _bridge_env() -> dict[str, str]:
    return {
        "AWS_REGION": "us-east-1",
        "AWS_BEARER_TOKEN_BEDROCK": "fake-bedrock",
        "NEXTSEEK_URL": "https://nx.example.com",
        "NEXTSEEK_BASE_URL": "https://nx.example.com",
        "DMAC_PATH_MAPPINGS": '{"x":1}',
    }


class _StubWebSocket:
    """Stub WebSocket capturing every send_json frame."""

    def __init__(self, incoming: list[dict[str, Any]] | None = None) -> None:
        self.sent_frames: list[dict[str, Any]] = []
        self._incoming = list(incoming or [])
        self.closed = False
        self.close_code: int | None = None
        from starlette.websockets import WebSocketState

        self.client_state = WebSocketState.CONNECTED

    async def send_json(self, frame: dict[str, Any]) -> None:
        self.sent_frames.append(frame)

    async def receive_json(self) -> dict[str, Any]:
        if not self._incoming:
            from starlette.websockets import WebSocketDisconnect

            raise WebSocketDisconnect(code=1000)
        return self._incoming.pop(0)

    async def accept(self, subprotocol: str | None = None) -> None:
        pass

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


def _make_ns_jsonl_stream(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    """Build a Docker stdcopy multi-frame stdout stream carrying JSONL events."""
    lines = [
        json.dumps({"event": name, "payload": payload}) + "\n"
        for name, payload in events
    ]
    return _make_stdcopy_stdout_stream(lines)


def _make_stdcopy_stdout_stream(lines: list[str | bytes]) -> bytes:
    """Build a Docker stdcopy multi-frame stdout stream."""
    out = bytearray()
    for line in lines:
        body = line.encode("utf-8") if isinstance(line, str) else line
        header = bytes([1, 0, 0, 0]) + struct.pack(">I", len(body))
        out.extend(header + body)
    return bytes(out)


class _RawSocketFake:
    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)
        self.sent = bytearray()
        self.shutdown_called: int | None = None
        self.closed = False

    def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def recv(self, n: int) -> bytes:
        return self.read(n)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def shutdown(self, how: int) -> None:
        self.shutdown_called = how

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def allow_unix_socket_only():
    """Permit asyncio's AF_UNIX self-pipe while keeping host sockets blocked."""
    try:
        import pytest_socket
    except ImportError:  # pragma: no cover
        yield
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("nope", False),
    ],
)
def test_router_enabled_truthiness(value: str, expected: bool, monkeypatch) -> None:
    from dmac_assistant.ws import _router_enabled

    monkeypatch.setenv("DMAC_ROUTER_ENABLED", value)
    assert _router_enabled() is expected


def test_router_enabled_unset_is_false(monkeypatch) -> None:
    from dmac_assistant.ws import _router_enabled

    monkeypatch.delenv("DMAC_ROUTER_ENABLED", raising=False)
    assert _router_enabled() is False


@pytest.mark.asyncio
async def test_route_decided_emitted_for_cc_route(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.router.baml_client.types import (
        ModelClass,
        Route,
        RouterDecision,
    )
    from dmac_assistant.ws import _dispatch_one_turn

    ws = _StubWebSocket()
    decision = RouterDecision(
        route=Route.ContainerCC,
        model_class=ModelClass.Sonnet,
        reasoning="picked cc",
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return decision

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    monkeypatch.setattr(
        "dmac_assistant.ws._dispatch_cc_turn",
        AsyncMock(return_value=(True, True, "sess-1")),
    )
    monkeypatch.setattr(
        "dmac_assistant.router.models.resolve", lambda mc: MODEL_ID_SONNET
    )

    await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="hello",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
    )

    assert ws.sent_frames[0] == {
        "type": "route_decided",
        "route": "container_cc",
        "model_class": "sonnet",
    }


@pytest.mark.asyncio
async def test_route_decided_emitted_for_ns_route(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.router.baml_client.types import Route, RouterDecision
    from dmac_assistant.ws import _dispatch_one_turn

    ws = _StubWebSocket()
    decision = RouterDecision(
        route=Route.NextseekQuery,
        model_class=None,
        reasoning="picked ns",
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return decision

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    monkeypatch.setattr("dmac_assistant.ws._dispatch_ns_turn", AsyncMock())

    await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="find me samples",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
    )

    rd = ws.sent_frames[0]
    assert rd == {
        "type": "route_decided",
        "route": "nextseek_query",
        "model_class": None,
    }
    assert "session_id" not in rd


@pytest.mark.asyncio
async def test_container_cc_always_dispatches_fixed_opus_model(
    tmp_path: Path, monkeypatch
) -> None:
    # OI-5: the router no longer selects a model class. A container_cc decision
    # with model_class=None must dispatch the fixed Opus 4.8 id (resolve_cc_model)
    # — there is no longer a Sonnet substitution — and route_decided carries the
    # null model_class through unchanged.
    from dmac_assistant.router.baml_client.types import Route, RouterDecision
    from dmac_assistant.ws import _dispatch_one_turn

    ws = _StubWebSocket()
    decision = RouterDecision(
        route=Route.ContainerCC,
        model_class=None,
        reasoning="router returned cc without a model class",
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return decision

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    dispatch_cc_mock = AsyncMock(return_value=(True, True, "sess-1"))
    monkeypatch.setattr("dmac_assistant.ws._dispatch_cc_turn", dispatch_cc_mock)
    monkeypatch.setattr(
        "dmac_assistant.router.models.resolve_cc_model", lambda: MODEL_ID_OPUS
    )

    await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="hello",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
    )

    assert ws.sent_frames[0]["model_class"] is None
    assert dispatch_cc_mock.call_args.kwargs["model_id"] == MODEL_ID_OPUS


@pytest.mark.asyncio
async def test_unrelated_route_emits_canned_message_and_spawns_no_container(
    tmp_path: Path, monkeypatch
) -> None:
    # OI-4: an `unrelated` decision emits route_decided + the canned
    # assistant_message + a terminal session_ended, and NEVER dispatches a CC
    # or NS turn (no container is touched).
    from dmac_assistant.router.baml_client.types import Route, RouterDecision
    from dmac_assistant.ws import _UNRELATED_CANNED_TEXT, _dispatch_one_turn

    ws = _StubWebSocket()
    decision = RouterDecision(
        route=Route.Unrelated,
        model_class=None,
        reasoning="celebrity gossip, unrelated to the lab",
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return decision

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    cc_mock = AsyncMock(return_value=(True, True, "sess-1"))
    ns_mock = AsyncMock()
    monkeypatch.setattr("dmac_assistant.ws._dispatch_cc_turn", cc_mock)
    monkeypatch.setattr("dmac_assistant.ws._dispatch_ns_turn", ns_mock)

    result = await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="When is Taylor Swift getting married to Travis Kelce?",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
    )

    types = [frame["type"] for frame in ws.sent_frames]
    assert types == ["route_decided", "assistant_message", "session_ended"]
    assert ws.sent_frames[0]["route"] == "unrelated"
    assert ws.sent_frames[1]["content"] == _UNRELATED_CANNED_TEXT
    # session_ended carries no session_id — an unrelated turn ends no session.
    assert ws.sent_frames[2]["session_id"] is None
    cc_mock.assert_not_awaited()
    ns_mock.assert_not_awaited()
    # 3-tuple contract preserved; no session state changed.
    assert result == (False, False, None)


@pytest.mark.asyncio
async def test_ns_dispatch_emits_session_started_before_event_frames(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.containers import BridgeAttachSocket
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()
    stream_bytes = _make_ns_jsonl_stream(
        [
            ("agent_started", {"agent": "parser"}),
            ("query_complete", {"reply": "Found 3 samples.", "bundle_id": "b-1"}),
        ]
    )
    fake_sock = BridgeAttachSocket(_RawSocketFake(stream_bytes))
    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: fake_sock)

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="user-key-1",
    )

    types = [f["type"] for f in ws.sent_frames]
    assert types[0] == "session_started"
    assert "tool_use" in types
    assert types[-1] == "session_ended"
    assert types.index("tool_use") < types.index("session_ended")


@pytest.mark.asyncio
async def test_ns_session_id_format_matches_ns_hex12(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()

    class _EmptySock:
        def read_event_line(self) -> str | None:
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: _EmptySock())

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="user-key-1",
    )

    session_started_frames = [
        f for f in ws.sent_frames if f.get("type") == "session_started"
    ]
    assert session_started_frames
    assert NS_SESSION_RE.fullmatch(session_started_frames[0]["session_id"])


@pytest.mark.asyncio
async def test_multi_turn_ns_then_ns_emits_all_terminals(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.containers import BridgeAttachSocket
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()

    def make_sock(events):
        return BridgeAttachSocket(_RawSocketFake(_make_ns_jsonl_stream(events)))

    socks = iter(
        [
            make_sock([("query_complete", {"reply": "turn 1 done"})]),
            make_sock([("query_complete", {"reply": "turn 2 done"})]),
        ]
    )
    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: next(socks))

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="k",
    )
    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi again",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="k",
    )

    assert sum(1 for f in ws.sent_frames if f.get("type") == "session_started") == 2
    assert sum(1 for f in ws.sent_frames if f.get("type") == "session_ended") == 2


@pytest.mark.asyncio
async def test_cc_dispatch_calls_primitive_with_resolved_model_id(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()

    class _MinimalSock:
        def read_frame(self) -> tuple[str, bytes] | None:
            return None

        def close(self) -> None:
            pass

    invocations: list[dict[str, Any]] = []

    def fake_primitive(container, **kwargs):
        del container
        invocations.append(kwargs)
        return _MinimalSock()

    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", fake_primitive)

    await _dispatch_cc_turn(
        websocket=ws,
        container=object(),
        query="hi",
        model_id=MODEL_ID_HAIKU,
        session_id="abc-resume",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id="abc-resume",
    )

    assert invocations[0]["model_id"] == MODEL_ID_HAIKU
    assert invocations[0]["session_id"] == "abc-resume"
    assert invocations[0]["query"] == "hi"


@pytest.mark.asyncio
async def test_cc_dispatch_fires_post_turn_callback_on_result(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.containers import BridgeAttachSocket
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()
    stream_bytes = _make_stdcopy_stdout_stream(
        [
            json.dumps(
                {"type": "system", "subtype": "init", "session_id": "sess-cc"}
            )
            + "\n",
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "done"}],
                    },
                }
            )
            + "\n",
            json.dumps({"type": "result"}) + "\n",
        ]
    )
    fake_sock = BridgeAttachSocket(_RawSocketFake(stream_bytes))
    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", lambda *a, **kw: fake_sock)
    copied: list[str] = []

    async def post_turn_callback() -> None:
        copied.append("copied")

    started, ended, sid = await _dispatch_cc_turn(
        websocket=ws,
        container=object(),
        query="hi",
        model_id=MODEL_ID_SONNET,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id=None,
        post_turn_callback=post_turn_callback,
    )

    assert (started, ended, sid) == (True, True, "sess-cc")
    assert copied == ["copied"]
    assert [f["type"] for f in ws.sent_frames] == [
        "session_started",
        "assistant_message",
        "session_ended",
    ]


@pytest.mark.asyncio
async def test_cc_dispatch_flushes_partial_init_and_synthetic_end_copies(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.containers import BridgeAttachSocket
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()
    stream_bytes = _make_stdcopy_stdout_stream(
        [
            json.dumps(
                {"type": "system", "subtype": "init", "session_id": "sess-flush"}
            )
            + "\n",
            "{not-json",
        ]
    )
    fake_sock = BridgeAttachSocket(_RawSocketFake(stream_bytes))
    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", lambda *a, **kw: fake_sock)
    copied: list[str] = []

    async def post_turn_callback() -> None:
        copied.append("copied")

    started, ended, sid = await _dispatch_cc_turn(
        websocket=ws,
        container=object(),
        query="hi",
        model_id=MODEL_ID_SONNET,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id=None,
        post_turn_callback=post_turn_callback,
    )

    assert (started, ended, sid) == (True, True, "sess-flush")
    assert copied == ["copied"]
    assert [f["type"] for f in ws.sent_frames] == [
        "session_started",
        "error",
        "session_ended",
    ]


@pytest.mark.asyncio
async def test_cc_dispatch_ignores_stderr_frames(tmp_path: Path, monkeypatch) -> None:
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()

    class _StderrSock:
        def __init__(self) -> None:
            self._frames: list[tuple[str, bytes] | None] = [
                ("stderr", b"diagnostic"),
                None,
            ]

        def read_frame(self) -> tuple[str, bytes] | None:
            return self._frames.pop(0)

        def close(self) -> None:
            pass

    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", lambda *a, **kw: _StderrSock())

    started, ended, sid = await _dispatch_cc_turn(
        websocket=ws,
        container=object(),
        query="hi",
        model_id=MODEL_ID_SONNET,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id=None,
    )

    assert (started, ended, sid) == (False, False, None)
    assert ws.sent_frames == []


def test_start_container_runtime_mode_idle_sets_env_var(tmp_path: Path) -> None:
    from dmac_assistant.containers import build_container_spec

    spec = build_container_spec(
        _identity(),
        _config(tmp_path),
        image="img",
        session_id=None,
        bridge_env=_bridge_env(),
        runtime_mode="idle",
    )
    assert spec.environment.get("DMAC_RUNTIME_MODE") == "idle"


def test_start_container_default_runtime_mode_unset(tmp_path: Path) -> None:
    from dmac_assistant.containers import build_container_spec

    spec = build_container_spec(
        _identity(),
        _config(tmp_path),
        image="img",
        session_id=None,
        bridge_env=_bridge_env(),
    )
    assert "DMAC_RUNTIME_MODE" not in spec.environment


def test_start_container_command_override_empty_uses_entrypoint_default(
    tmp_path: Path,
) -> None:
    from dmac_assistant.containers import start_container

    captured: dict[str, Any] = {}

    class _FakeClient:
        class containers:
            @staticmethod
            def run(**kwargs):
                captured.update(kwargs)

                class _C:
                    id = "ctr-1"

                return _C()

    start_container(
        _identity(),
        image="img",
        session_id=None,
        bridge_env=_bridge_env(),
        config=_config(tmp_path),
        client=_FakeClient(),
        runtime_mode="idle",
        command_override=[],
    )

    assert captured["command"] == []
    assert captured["environment"]["DMAC_RUNTIME_MODE"] == "idle"


def test_route_alias_dict_maps_baml_enum_to_at_alias_string() -> None:
    from dmac_assistant.router.baml_client.types import Route
    from dmac_assistant.ws import _ROUTE_ALIAS

    assert _ROUTE_ALIAS[Route.NextseekQuery] == "nextseek_query"
    assert _ROUTE_ALIAS[Route.ContainerCC] == "container_cc"


def test_model_class_alias_dict_maps_baml_enum_to_at_alias_string() -> None:
    from dmac_assistant.router.baml_client.types import ModelClass
    from dmac_assistant.ws import _MODEL_CLASS_ALIAS

    assert _MODEL_CLASS_ALIAS[ModelClass.Sonnet] == "sonnet"
    assert _MODEL_CLASS_ALIAS[ModelClass.Haiku] == "haiku"
    assert _MODEL_CLASS_ALIAS[ModelClass.Opus] == "opus"


@pytest.mark.asyncio
async def test_cc_exec_failure_emits_cc_exec_failed_frame(
    tmp_path: Path, monkeypatch
) -> None:
    from docker.errors import APIError
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()

    def fake_primitive(*args, **kwargs):
        raise APIError("docker daemon unavailable")

    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", fake_primitive)

    await _dispatch_cc_turn(
        websocket=ws,
        container=object(),
        query="hi",
        model_id=MODEL_ID_SONNET,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id=None,
    )

    reasons = [f.get("reason") for f in ws.sent_frames if f.get("type") == "error"]
    assert "cc_exec_failed" in reasons


@pytest.mark.asyncio
async def test_ns_exec_failure_emits_ns_exec_failed_frame(
    tmp_path: Path, monkeypatch
) -> None:
    from docker.errors import APIError
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()

    def fake_primitive(*args, **kwargs):
        raise APIError("docker daemon unavailable")

    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", fake_primitive)

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="k",
    )

    reasons = [f.get("reason") for f in ws.sent_frames if f.get("type") == "error"]
    assert "ns_exec_failed" in reasons


@pytest.mark.asyncio
async def test_multi_turn_cc_then_ns_state_isolation(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.router.baml_client.types import (
        ModelClass,
        Route,
        RouterDecision,
    )
    from dmac_assistant.ws import _dispatch_one_turn

    ws = _StubWebSocket()
    decisions = iter(
        [
            RouterDecision(
                route=Route.ContainerCC,
                model_class=ModelClass.Sonnet,
                reasoning="cc",
            ),
            RouterDecision(
                route=Route.NextseekQuery,
                model_class=None,
                reasoning="ns",
            ),
        ]
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return next(decisions)

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    monkeypatch.setattr(
        "dmac_assistant.ws._dispatch_cc_turn",
        AsyncMock(return_value=(True, True, "cc-sess-1")),
    )
    monkeypatch.setattr("dmac_assistant.ws._dispatch_ns_turn", AsyncMock())
    monkeypatch.setattr(
        "dmac_assistant.router.models.resolve", lambda mc: MODEL_ID_SONNET
    )

    started1, ended1, sid1 = await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="cc query",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        ns_session_key="ws-key-1",
    )
    assert sid1 == "cc-sess-1"

    _, _, sid2 = await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="ns query",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=sid1,
        session_started_emitted=started1,
        session_ended_emitted=ended1,
        ns_session_key="ws-key-1",
    )
    assert sid2 == sid1

    rd_frames = [f for f in ws.sent_frames if f.get("type") == "route_decided"]
    assert rd_frames == [
        {"type": "route_decided", "route": "container_cc", "model_class": "sonnet"},
        {"type": "route_decided", "route": "nextseek_query", "model_class": None},
    ]


@pytest.mark.asyncio
async def test_ns_route_fires_post_turn_callback_after_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.router.baml_client.types import Route, RouterDecision
    from dmac_assistant.ws import _dispatch_one_turn

    ws = _StubWebSocket()
    decision = RouterDecision(
        route=Route.NextseekQuery,
        model_class=None,
        reasoning="picked ns",
    )

    async def fake_route(query: str) -> RouterDecision:
        del query
        return decision

    fake_agent = AsyncMock()
    fake_agent.route = fake_route
    monkeypatch.setattr("dmac_assistant.ws._get_router_agent", lambda: fake_agent)
    monkeypatch.setattr("dmac_assistant.ws._dispatch_ns_turn", AsyncMock())
    copied: list[str] = []

    async def post_turn_callback() -> None:
        copied.append("copied")

    await _dispatch_one_turn(
        websocket=ws,
        container=object(),
        query="find me samples",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        post_turn_callback=post_turn_callback,
    )

    assert copied == ["copied"]


@pytest.mark.asyncio
async def test_cc_dispatch_timeout_calls_kill_exec_pid_and_emits_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.ws import _dispatch_cc_turn

    ws = _StubWebSocket()

    class _HangingSock:
        def __init__(self) -> None:
            self._exec_id = "exec-hang"
            self._closed = False

        def read_frame(self) -> tuple[str, bytes] | None:
            import time as _t

            _t.sleep(5.0)
            return None

        def close(self) -> None:
            self._closed = True

    hang_sock = _HangingSock()
    monkeypatch.setattr("dmac_assistant.ws.exec_cc_turn", lambda *a, **kw: hang_sock)
    monkeypatch.setattr("dmac_assistant.ws._CC_TURN_TIMEOUT_SECONDS", 0.05)
    killed: list[tuple[Any, str]] = []

    def fake_kill(container: Any, exec_id: str, *, client: Any = None) -> None:
        del client
        killed.append((container, exec_id))

    monkeypatch.setattr("dmac_assistant.ws.kill_exec_pid", fake_kill)

    sentinel_container = object()
    await _dispatch_cc_turn(
        websocket=ws,
        container=sentinel_container,
        query="hi",
        model_id=MODEL_ID_SONNET,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        current_session_id=None,
        session_started_emitted=False,
        session_ended_emitted=False,
        requested_session_id=None,
    )

    assert killed == [(sentinel_container, "exec-hang")]
    reasons = [f.get("reason") for f in ws.sent_frames if f.get("type") == "error"]
    assert "exec_timeout" in reasons


@pytest.mark.asyncio
async def test_ns_dispatch_timeout_calls_kill_exec_pid_and_emits_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()

    class _HangingSock:
        def __init__(self) -> None:
            self._exec_id = "exec-ns-hang"
            self._closed = False

        def read_event_line(self) -> str | None:
            import time as _t

            _t.sleep(5.0)
            return None

        def close(self) -> None:
            self._closed = True

    hang_sock = _HangingSock()
    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: hang_sock)
    monkeypatch.setattr("dmac_assistant.ws._NS_TURN_TIMEOUT_SECONDS", 0.05)
    killed: list[tuple[Any, str]] = []

    def fake_kill(container: Any, exec_id: str, *, client: Any = None) -> None:
        del client
        killed.append((container, exec_id))

    monkeypatch.setattr("dmac_assistant.ws.kill_exec_pid", fake_kill)

    sentinel_container = object()
    await _dispatch_ns_turn(
        websocket=ws,
        container=sentinel_container,
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="k",
    )

    assert killed == [(sentinel_container, "exec-ns-hang")]
    reasons = [f.get("reason") for f in ws.sent_frames if f.get("type") == "error"]
    assert "exec_timeout" in reasons
    types = [f.get("type") for f in ws.sent_frames]
    assert types[-1] == "session_ended"


@pytest.mark.asyncio
async def test_ns_dispatch_drops_invalid_json_and_post_terminal_events(
    tmp_path: Path, monkeypatch
) -> None:
    from dmac_assistant.ws import _dispatch_ns_turn

    ws = _StubWebSocket()

    class _LineSock:
        def __init__(self) -> None:
            self._lines = iter(
                [
                    "{not-json",
                    json.dumps(
                        {
                            "event": "query_complete",
                            "payload": {"reply": "done"},
                        }
                    ),
                    json.dumps(
                        {
                            "event": "agent_started",
                            "payload": {"agent": "late"},
                        }
                    ),
                    None,
                ]
            )

        def read_event_line(self) -> str | None:
            return next(self._lines)

        def close(self) -> None:
            pass

    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: _LineSock())

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="k",
    )

    types = [f.get("type") for f in ws.sent_frames]
    assert types == ["session_started", "assistant_message", "session_ended"]
    assistant_contents = [
        f.get("content")
        for f in ws.sent_frames
        if f.get("type") == "assistant_message"
    ]
    assert assistant_contents == ["done"]


def test_router_on_branch_is_inserted_after_dir_creation_block() -> None:
    from pathlib import Path as _Path

    import dmac_assistant.ws as _ws_mod

    src = _Path(_ws_mod.__file__).read_text(encoding="utf-8")
    idx_def_ensure = src.find("def ensure_user_output_dir(")
    assert idx_def_ensure != -1
    idx_after_def = src.find("\n", idx_def_ensure) + 1
    idx_ensure_user_output_dir_call = src.find(
        "ensure_user_output_dir(", idx_after_def
    )

    idx_build_bridge_env = src.find("bridge_env = _build_bridge_env(")
    idx_scratch_user = src.find("scratch_root / identity.user_id")
    idx_scratch_mkdir_call = (
        src.find(".mkdir(", idx_scratch_user) if idx_scratch_user != -1 else -1
    )
    idx_router_enabled = src.find("_router_enabled()")

    assert idx_build_bridge_env != -1
    assert idx_ensure_user_output_dir_call != -1
    assert idx_scratch_mkdir_call != -1
    assert idx_router_enabled != -1
    assert idx_build_bridge_env < idx_ensure_user_output_dir_call
    assert idx_ensure_user_output_dir_call < idx_scratch_mkdir_call
    assert idx_scratch_mkdir_call < idx_router_enabled


def test_router_on_path_preserves_post_turn_copy_hook() -> None:
    from pathlib import Path as _Path

    import dmac_assistant.ws as _ws_mod

    src = _Path(_ws_mod.__file__).read_text(encoding="utf-8")
    idx_router_on = src.find("async def _chat_ws_router_on(")
    assert idx_router_on != -1
    idx_dispatch_one_turn = src.find("\n\nasync def _dispatch_one_turn", idx_router_on)
    router_on_src = src[idx_router_on:idx_dispatch_one_turn]
    assert "pre_turn_files = snapshot_scratch_files(" in router_on_src
    assert "async def fire_post_turn_copy()" in router_on_src
    assert "dispatch_post_turn_copy" in router_on_src
    assert "post_turn_callback=fire_post_turn_copy" in router_on_src


# Phase 7 residual #1 visibility (2026-05-18): NS-route stderr capture.


def test_open_ns_stderr_capture_returns_none_when_env_var_unset(monkeypatch) -> None:
    """Default-OFF: no env var, no file handle, no side effects."""
    from dmac_assistant.ws import _open_ns_stderr_capture

    monkeypatch.delenv("DMAC_BRIDGE_NS_STDERR_DIR", raising=False)
    assert _open_ns_stderr_capture("ns-abcdef012345") is None


def test_open_ns_stderr_capture_creates_dir_and_returns_appendable_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Env var set: directory auto-created, file opened in binary append mode,
    file path uses ns_session_id basename."""
    capture_dir = tmp_path / "ns-stderr"
    # Deliberately do not pre-create capture_dir; the helper must mkdir it.
    monkeypatch.setenv("DMAC_BRIDGE_NS_STDERR_DIR", str(capture_dir))

    from dmac_assistant.ws import _open_ns_stderr_capture

    fh = _open_ns_stderr_capture("ns-abcdef012345")
    try:
        assert fh is not None
        assert fh.mode == "ab"
        # Write + reopen: append mode must preserve prior content (per-turn
        # files are append-only so re-execs against the same session id
        # accumulate). With `wb` you would clobber.
        fh.write(b"line1\n")
        fh.flush()
        fh.close()
        fh2 = _open_ns_stderr_capture("ns-abcdef012345")
        try:
            assert fh2 is not None
            fh2.write(b"line2\n")
        finally:
            fh2.close()
        expected_path = capture_dir / "ns-abcdef012345.stderr.log"
        assert expected_path.exists()
        assert expected_path.read_bytes() == b"line1\nline2\n"
    finally:
        if not fh.closed:  # type: ignore[union-attr]
            fh.close()  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "bad_session_id",
    [
        "../etc/passwd",  # path traversal
        "ns-XYZ",  # uppercase, wrong length
        "session-1",  # no `ns-` prefix
        "ns-abcdef01234",  # 11 chars, not 12
        "ns-abcdef0123456",  # 13 chars, not 12
        "ns-g0e0e0e0e0e0",  # contains non-hex digit
    ],
)
def test_open_ns_stderr_capture_rejects_malformed_session_id(
    bad_session_id: str, tmp_path: Path, monkeypatch
) -> None:
    """Path-traversal defense: only ^ns-[0-9a-f]{12}$ is allowed (T3.2 spec
    L424). A malformed id makes the helper return None and the directory
    untouched (no file leaked)."""
    monkeypatch.setenv("DMAC_BRIDGE_NS_STDERR_DIR", str(tmp_path))

    from dmac_assistant.ws import _open_ns_stderr_capture

    assert _open_ns_stderr_capture(bad_session_id) is None
    # Directory must remain empty (no stray files written via the bad id).
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_dispatch_ns_turn_wires_sock_stderr_sink_when_capture_env_set(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end wiring: when DMAC_BRIDGE_NS_STDERR_DIR is set, the dispatch
    helper opens the per-session file and attaches it as sock.stderr_sink so
    subsequent BridgeAttachSocket.read_event_line writes flow into it."""
    from dmac_assistant.containers import BridgeAttachSocket
    from dmac_assistant.ws import _dispatch_ns_turn

    capture_dir = tmp_path / "ns-stderr"
    monkeypatch.setenv("DMAC_BRIDGE_NS_STDERR_DIR", str(capture_dir))

    ws = _StubWebSocket()
    # Stream: one stderr frame carrying the kind of debug text we want to
    # capture, followed by an empty stdout (no events) so dispatch finishes.
    stderr_payload = b"[DEBUG][PARSER] Exception or parse error: StructuredOutputError(...)\n"
    raw = _RawSocketFake(_make_stderr_then_eof(stderr_payload))
    fake_sock = BridgeAttachSocket(raw)
    monkeypatch.setattr("dmac_assistant.ws.exec_ns_turn", lambda *a, **kw: fake_sock)

    await _dispatch_ns_turn(
        websocket=ws,
        container=object(),
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env(),
        ns_session_key="user-key-1",
    )

    # Exactly one capture file should exist, named after the synthesized
    # ns_session_id, and should contain the verbatim stderr payload.
    capture_files = list(capture_dir.iterdir())
    assert len(capture_files) == 1
    assert capture_files[0].name.endswith(".stderr.log")
    name_root = capture_files[0].name[: -len(".stderr.log")]
    assert NS_SESSION_RE.fullmatch(name_root), (
        f"capture file name root {name_root!r} did not match ns- format"
    )
    assert capture_files[0].read_bytes() == stderr_payload


def _make_stderr_then_eof(payload: bytes) -> bytes:
    """Helper: one stderr frame followed by socket EOF (no stdout)."""
    header = bytes([2, 0, 0, 0]) + struct.pack(">I", len(payload))
    return header + payload
