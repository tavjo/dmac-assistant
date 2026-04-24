"""Multi-turn WebSocket: one socket stays open across per-turn ``session_ended``."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dmac_assistant.auth import TokenStore
from tests.integration.test_ws_endpoint import (
    _assistant_text_event,
    _init_event,
    _issued_token,
    _make_app,
    _result_event,
    allow_unix_socket_only,
    bridge_config,
    configured_env,
    token_store,
)


def test_two_turns_one_socket_happy_path(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    sid = "11111111-1111-1111-1111-111111111111"
    frames = [
        ("stdout", _init_event(sid)),
        ("stdout", _assistant_text_event("answer-one")),
        ("stdout", _result_event()),
        ("stdout", _assistant_text_event("answer-two")),
        ("stdout", _result_event()),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "q1", "new_session": True}
            )
            seen: list[dict] = []
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
            ws.send_json({"type": "user_message", "content": "q2"})
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break

    starts = [m for m in seen if m.get("type") == "session_started"]
    ends = [m for m in seen if m.get("type") == "session_ended"]
    assert len(starts) == 1
    assert len(ends) == 2
    assert starts[0]["session_id"] == sid
    stdin = _state["fake_socket"].stdin_writes
    assert len(stdin) == 2
    assert b"q1" in stdin[0] and b"q2" in stdin[1]


def test_session_started_emitted_once_across_turns(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    sid = "22222222-2222-2222-2222-222222222222"
    frames = [
        ("stdout", _init_event(sid)),
        ("stdout", _assistant_text_event("a")),
        ("stdout", _result_event()),
        ("stdout", _assistant_text_event("b")),
        ("stdout", _result_event()),
        None,
    ]
    app, _state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "t1", "new_session": True}
            )
            seen = []
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
            ws.send_json({"type": "user_message", "content": "t2"})
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
    assert sum(1 for m in seen if m.get("type") == "session_started") == 1


def test_session_ended_emitted_per_turn(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    sid = "33333333-3333-3333-3333-333333333333"
    frames = [
        ("stdout", _init_event(sid)),
        ("stdout", _assistant_text_event("x")),
        ("stdout", _result_event()),
        ("stdout", _assistant_text_event("y")),
        ("stdout", _result_event()),
        None,
    ]
    app, _ = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "u1", "new_session": True}
            )
            seen = []
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
            ws.send_json({"type": "user_message", "content": "u2"})
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
    ended = [m for m in seen if m.get("type") == "session_ended"]
    assert len(ended) == 2
    assert ended[0].get("session_id") == sid
    assert ended[1].get("session_id") == sid


def test_stdin_writes_forwarded_per_turn(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    sid = "44444444-4444-4444-4444-444444444444"
    frames = [
        ("stdout", _init_event(sid)),
        ("stdout", _assistant_text_event("r")),
        ("stdout", _result_event()),
        None,
    ]
    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "hello-turn", "new_session": True}
            )
            while ws.receive_json().get("type") != "session_ended":
                pass
    assert len(state["fake_socket"].stdin_writes) == 1
    raw = state["fake_socket"].stdin_writes[0].decode()
    assert "hello-turn" in raw


def test_attach_eof_after_turn_emits_session_ended_then_closes(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """EOF (read_frame None) ends the read loop; client eventually gets disconnect."""
    sid = "55555555-5555-5555-5555-555555555555"
    frames = [
        ("stdout", _init_event(sid)),
        ("stdout", _assistant_text_event("z")),
        ("stdout", _result_event()),
        None,
    ]
    app, _ = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "only", "new_session": True}
            )
            got_ended = False
            while True:
                try:
                    m = ws.receive_json()
                except WebSocketDisconnect:
                    break
                if m.get("type") == "session_ended":
                    got_ended = True
            assert got_ended


def test_malformed_init_closes_1011(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    bad = (
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "",
                "model": "x",
                "cwd": "/home/user",
            }
        )
        + "\n"
    ).encode()
    frames = [("stdout", bad), None]
    app, _ = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                "/ws/chat", subprotocols=["dmac.bearer", token]
            ) as ws:
                ws.send_json({"type": "user_message", "content": "x", "new_session": True})
                while True:
                    ws.receive_json()
    assert exc.value.code == 1011


def test_new_session_true_mid_socket_re_emits_session_started(
    allow_unix_socket_only,
    configured_env,
    monkeypatch: pytest.MonkeyPatch,
    token_store: TokenStore,
) -> None:
    """Second user frame may request ``new_session``; bridge forwards it on stdin."""
    sid1 = "66666666-6666-6666-6666-666666666666"
    sid2 = "77777777-7777-7777-7777-777777777777"
    frames = [
        ("stdout", _init_event(sid1)),
        ("stdout", _assistant_text_event("t1")),
        ("stdout", _result_event()),
        ("stdout", _init_event(sid2)),
        ("stdout", _assistant_text_event("t2")),
        ("stdout", _result_event()),
        None,
    ]
    app, state = _make_app(monkeypatch, token_store=token_store, frames=frames)
    token = _issued_token(token_store)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat", subprotocols=["dmac.bearer", token]
        ) as ws:
            ws.send_json(
                {"type": "user_message", "content": "a", "new_session": True}
            )
            seen = []
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
            ws.send_json(
                {"type": "user_message", "content": "b", "new_session": True}
            )
            while True:
                m = ws.receive_json()
                seen.append(m)
                if m.get("type") == "session_ended":
                    break
    starts = [m for m in seen if m.get("type") == "session_started"]
    assert len(starts) == 2
    assert starts[0]["session_id"] == sid1
    assert starts[1]["session_id"] == sid2
    second = state["fake_socket"].stdin_writes[1].decode()
    assert "new_session" in second

