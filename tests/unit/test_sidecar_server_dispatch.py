"""handle_message validates the T2 envelope, routes to run_op, maps errors to codes."""
import json
import sys
import types

import pytest

from sidecar.app import server
from sidecar.app.contract import NsLogin


@pytest.fixture
def allow_unix_socket_only():
    """pytest-asyncio's loop creation calls socketpair() on AF_UNIX; the
    repo-wide ``--disable-socket`` blocks it. Same workaround used by
    ``tests/unit/test_router_judge.py`` / ``test_app_health.py`` / ``test_auth.py``.
    """
    import pytest_socket

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.fixture
def patched(monkeypatch, allow_unix_socket_only):
    def fake_run_op(op, args, **k):
        if op == "entity":
            return {"echo": args}
        raise server.ops.OpValidationError("bad")
    monkeypatch.setattr(server.ops, "run_op", fake_run_op)
    # config + session factories stubbed so no chat_nextseek / DB is touched
    monkeypatch.setattr(server, "_build_user_config", lambda login: object())
    monkeypatch.setattr(server, "_build_user_session", lambda login, cfg: object())
    # DOCUMENTED SEAM (T4): the spec fixture omits these two; without stubbing them
    # the real builders import the not-yet-built T5/T7 modules (sidecar.app.write_gate,
    # sidecar.app.staging) and _CFG is None, so the setup try-block would raise and
    # test_ok_envelope would wrongly hit CONFIG_ERROR. Stub to the T4 passthrough defaults,
    # consistent with the fixture's own docstring.
    monkeypatch.setattr(server, "_build_write_gate", lambda: server.ops.ALLOW_ALL)
    monkeypatch.setattr(server, "_build_stage", lambda rid, login: server.ops.NO_STAGE)


def _msg(op, args):
    return json.dumps({"op": op, "args": args,
                       "ns_login": {"api_user": "u", "api_pass": "p"},
                       "request_id": "11111111-1111-4111-8111-111111111111"})


@pytest.mark.asyncio
async def test_ok_envelope(patched):
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "ok" and resp["result"]["echo"] == {"query": "x"}
    assert resp["request_id"] == "11111111-1111-4111-8111-111111111111"
    assert resp["error"] is None


@pytest.mark.asyncio
async def test_unknown_op_maps_to_validation(patched):
    resp = json.loads(await server.handle_message(_msg("query", {})))  # unknown op rejected by contract
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_malformed_op_args_map_to_validation(patched):
    # vet finding 15: missing required arg → VALIDATION (exit 3), NOT AGENT_FAILED (exit 4).
    resp = json.loads(await server.handle_message(_msg("entity", {})))  # missing query
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_malformed_json_is_transport_error(patched):
    resp = json.loads(await server.handle_message("{not json"))
    assert resp["error"]["code"] in ("VALIDATION", "TRANSPORT_ERROR")


@pytest.mark.asyncio
async def test_config_error_on_setup_failure(patched, monkeypatch):
    def boom(login):
        raise RuntimeError("db down")
    monkeypatch.setattr(server, "_build_user_config", boom)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "CONFIG_ERROR"


@pytest.mark.asyncio
async def test_run_op_validation_maps_to_validation(patched, monkeypatch):
    def raise_val(op, args, **k):
        raise server.ops.OpValidationError("nope")
    monkeypatch.setattr(server.ops, "run_op", raise_val)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"


@pytest.mark.asyncio
async def test_write_blocked_maps_to_write_blocked(patched, monkeypatch):
    def raise_wb(op, args, **k):
        raise server.ops.WriteBlockedError("blocked")
    monkeypatch.setattr(server.ops, "run_op", raise_wb)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_downstream_failure_maps_to_agent_failed(patched, monkeypatch):
    def boom(op, args, **k):
        raise RuntimeError("neo4j exploded")
    monkeypatch.setattr(server.ops, "run_op", boom)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "AGENT_FAILED"


# ---- the T4-seam builder wiring (real bodies, with the T5/T6/T7 modules faked) -----
def test_build_user_config_binds_login_and_returns_chatconfig(monkeypatch):
    captured = {}
    cfgmod = types.ModuleType("chat_nextseek.config")

    class ChatConfig:
        def __init__(self, d):
            captured["d"] = d

    cfgmod.ChatConfig = ChatConfig
    monkeypatch.setitem(sys.modules, "chat_nextseek.config", cfgmod)
    monkeypatch.setenv("API_USER", "")  # register for monkeypatch cleanup
    monkeypatch.setenv("API_PASS", "")

    import os
    out = server._build_user_config(NsLogin(api_user="alice", api_pass="pw"))
    assert isinstance(out, ChatConfig)
    assert os.environ["API_USER"] == "alice"  # per-call user login bound (U-2)
    assert captured["d"] == {}


def test_build_user_session_calls_make_session(monkeypatch):
    captured = {}
    sessmod = types.ModuleType("sidecar.app.sessions")

    def make_session(login, config, cfg):
        captured["args"] = (login, config, cfg)
        return "SESSION"

    sessmod.make_session = make_session
    monkeypatch.setitem(sys.modules, "sidecar.app.sessions", sessmod)
    login = NsLogin(api_user="u", api_pass="p")
    cfg = object()
    assert server._build_user_session(login, cfg) == "SESSION"
    assert captured["args"] == (login, cfg, server._CFG)


def test_build_write_gate_calls_build_gate(monkeypatch):
    captured = {}
    wgmod = types.ModuleType("sidecar.app.write_gate")

    def build_gate(cfg):
        captured["cfg"] = cfg
        return "GATE"

    wgmod.build_gate = build_gate
    monkeypatch.setitem(sys.modules, "sidecar.app.write_gate", wgmod)
    assert server._build_write_gate() == "GATE"
    assert captured["cfg"] is server._CFG


def test_build_stage_calls_make_stage(monkeypatch):
    captured = {}
    stmod = types.ModuleType("sidecar.app.staging")

    def make_stage(cfg, login, request_id):
        captured["args"] = (cfg, login, request_id)
        return "STAGE"

    stmod.make_stage = make_stage
    monkeypatch.setitem(sys.modules, "sidecar.app.staging", stmod)
    login = NsLogin(api_user="u", api_pass="p")
    assert server._build_stage("rid-1", login) == "STAGE"
    assert captured["args"] == (server._CFG, login, "rid-1")
