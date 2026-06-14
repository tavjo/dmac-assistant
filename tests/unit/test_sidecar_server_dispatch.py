"""handle_message validates the T2 envelope, routes to run_op, maps errors to codes.
T16: _build_user_session REMOVED; _build_stage_bytes ADDED; no env mutation for user creds;
AUTH_FAILED and TRANSPORT_ERROR now mapped; session=None passed to run_op.
"""
import json
import os
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
    # config factory stubbed so no HTTP / env mutation is touched
    monkeypatch.setattr(server, "_build_user_config", lambda login: object())
    # NOTE: _build_user_session has been REMOVED from server.py (T16)
    # DOCUMENTED SEAM (T4 updated T16): stub the four post-T16 builders.
    monkeypatch.setattr(server, "_build_write_gate", lambda: server.ops.ALLOW_ALL)
    monkeypatch.setattr(server, "_build_stage", lambda rid, login: server.ops.NO_STAGE)
    monkeypatch.setattr(server, "_build_stage_bytes",
                        lambda rid, login: (server.ops.NO_STAGE_BYTES, server.ops.NO_COMMIT))


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
async def test_int_request_id_returns_typed_validation(patched):
    raw = json.dumps({"op": "entity", "args": {"query": "x"},
                      "ns_login": {"api_user": "u", "api_pass": "p"},
                      "request_id": 123})
    resp = json.loads(await server.handle_message(raw))  # must RETURN, not raise
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"
    assert isinstance(resp["request_id"], str)


@pytest.mark.asyncio
async def test_null_request_id_returns_typed_validation(patched):
    raw = json.dumps({"op": "entity", "args": {"query": "x"},
                      "ns_login": {"api_user": "u", "api_pass": "p"},
                      "request_id": None})
    resp = json.loads(await server.handle_message(raw))  # must RETURN, not raise
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"
    assert isinstance(resp["request_id"], str)


@pytest.mark.asyncio
async def test_top_level_array_returns_typed_validation(patched):
    resp = json.loads(await server.handle_message('["not", "a", "dict"]'))
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"
    assert isinstance(resp["request_id"], str)


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
async def test_invalid_parser_plan_maps_to_validation(allow_unix_socket_only, monkeypatch):
    # T4 review fix 2 (server level): malformed parser_plan JSON → VALIDATION (exit-3
    # parity with the pre-sidecar runner), NOT AGENT_FAILED. Builders are stubbed as in
    # `patched`, but ops.run_op is left REAL so the ops._api_read fix is exercised.
    # T16: _build_user_session removed; _build_stage_bytes added.
    monkeypatch.setattr(server, "_build_user_config", lambda login: object())
    monkeypatch.setattr(server, "_build_write_gate", lambda: server.ops.ALLOW_ALL)
    monkeypatch.setattr(server, "_build_stage", lambda rid, login: server.ops.NO_STAGE)
    monkeypatch.setattr(server, "_build_stage_bytes",
                        lambda rid, login: (server.ops.NO_STAGE_BYTES, server.ops.NO_COMMIT))
    # The _api_read handler now raises OpValidationError directly from _load_parser_plan
    # before any HTTP call — no need to fake chat_nextseek modules.
    resp = json.loads(await server.handle_message(_msg("api-read", {"parser_plan": "{not json"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "VALIDATION"
    assert "parser_plan" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_write_blocked_maps_to_write_blocked(patched, monkeypatch):
    def raise_wb(op, args, **k):
        raise server.ops.WriteBlockedError("blocked")
    monkeypatch.setattr(server.ops, "run_op", raise_wb)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "WRITE_BLOCKED"


@pytest.mark.asyncio
async def test_staging_error_maps_to_staging_error(patched, monkeypatch):
    from sidecar.app import staging

    def raise_staging(op, args, **k):
        raise staging.StagingError("disk full")

    monkeypatch.setattr(server.ops, "run_op", raise_staging)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "STAGING_ERROR"
    assert "disk full" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_downstream_failure_maps_to_agent_failed(patched, monkeypatch):
    def boom(op, args, **k):
        raise RuntimeError("neo4j exploded")
    monkeypatch.setattr(server.ops, "run_op", boom)
    resp = json.loads(await server.handle_message(_msg("entity", {"query": "x"})))
    assert resp["status"] == "error" and resp["error"]["code"] == "AGENT_FAILED"


# ---- T16: new error mapping tests ----------------------------------------

def _stub_build_helpers(monkeypatch, *, config=True):
    if config:
        monkeypatch.setattr(server, "_build_user_config", lambda login: object())
    monkeypatch.setattr(server, "_build_write_gate", lambda: server.ops.ALLOW_ALL)
    monkeypatch.setattr(server, "_build_stage", lambda rid, login: server.ops.NO_STAGE)
    monkeypatch.setattr(server, "_build_stage_bytes",
                        lambda rid, login: (server.ops.NO_STAGE_BYTES, server.ops.NO_COMMIT))


@pytest.mark.asyncio
async def test_auth_failed_maps_to_AUTH_FAILED(monkeypatch, allow_unix_socket_only):
    _stub_build_helpers(monkeypatch)
    monkeypatch.setattr(server.ops, "run_op",
                        lambda *a, **k: (_ for _ in ()).throw(server.ops.AuthFailedError("bad creds")))
    frame = {"request_id": "11111111-1111-4111-8111-111111111111", "op": "entity",
             "args": {"query": "q"}, "ns_login": {"api_user": "u", "api_pass": "p"}}
    resp = json.loads(await server.handle_message(json.dumps(frame)))
    assert resp["error"]["code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_transport_error_maps_to_TRANSPORT_ERROR(monkeypatch, allow_unix_socket_only):
    _stub_build_helpers(monkeypatch)
    monkeypatch.setattr(server.ops, "run_op",
                        lambda *a, **k: (_ for _ in ()).throw(server.ops.TransportError("timeout")))
    frame = {"request_id": "22222222-2222-4222-8222-222222222222", "op": "entity",
             "args": {"query": "q"}, "ns_login": {"api_user": "u", "api_pass": "p"}}
    resp = json.loads(await server.handle_message(json.dumps(frame)))
    assert resp["error"]["code"] == "TRANSPORT_ERROR"


@pytest.mark.asyncio
async def test_no_env_mutation_for_user_creds(monkeypatch, allow_unix_socket_only):
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.setattr(server, "_CFG",
                        types.SimpleNamespace(nextseek_base_url="http://ns"))
    _stub_build_helpers(monkeypatch, config=False)  # do NOT stub _build_user_config
    monkeypatch.setattr(server.ops, "run_op", lambda *a, **k: {"ok": True})
    frame = {"request_id": "22222222-2222-4222-8222-222222222222", "op": "entity",
             "args": {"query": "q"}, "ns_login": {"api_user": "leak", "api_pass": "x"}}
    await server.handle_message(json.dumps(frame))
    assert os.environ.get("API_USER") != "leak"  # real builder passes creds as args, never to env


@pytest.mark.asyncio
async def test_server_threads_stage_bytes_into_run_op(monkeypatch, allow_unix_socket_only):
    _stub_build_helpers(monkeypatch)
    seen = {}

    def fake_run_op(op, args, *, config, session, write_gate, stage, stage_bytes, commit_bytes, **k):
        seen["stage_bytes"] = stage_bytes
        seen["commit_bytes"] = commit_bytes
        return {"summary": {}, "saved_files": {}, "rows": {}}

    monkeypatch.setattr(server.ops, "run_op", fake_run_op)
    frame = {"request_id": "33333333-3333-4333-8333-333333333333", "op": "report",
             "args": {"mode": "published", "project": "Published Data"},
             "ns_login": {"api_user": "u", "api_pass": "p"}}
    await server.handle_message(json.dumps(frame))
    assert callable(seen["stage_bytes"])
    assert callable(seen["commit_bytes"])


# ---- the T4-seam builder wiring (real bodies, with modules faked) -----------

def test_build_user_config_returns_ns_http_config(monkeypatch):
    """_build_user_config returns NsHttpConfig(base_url, auth) — no env mutation (T16)."""
    monkeypatch.setattr(server, "_CFG",
                        types.SimpleNamespace(nextseek_base_url="http://ns"))
    login = NsLogin(api_user="alice", api_pass="pw")
    cfg = server._build_user_config(login)
    assert cfg.base_url == "http://ns"
    assert cfg.auth == ("alice", "pw")
    # Critically: API_USER must NOT have been mutated into os.environ
    assert os.environ.get("API_USER") != "alice"


def test_build_write_gate_calls_build_gate_no_arg(monkeypatch):
    """_build_write_gate() calls no-arg build_gate() and returns the gate."""
    captured = {}
    wgmod = types.ModuleType("sidecar.app.write_gate")

    def build_gate():  # no args
        captured["called"] = True
        return "GATE"

    wgmod.build_gate = build_gate
    monkeypatch.setitem(import_modules := __import__("sys").modules, "sidecar.app.write_gate", wgmod)
    assert server._build_write_gate() == "GATE"
    assert captured.get("called") is True


def test_build_stage_calls_make_stage(monkeypatch):
    captured = {}
    stmod = types.ModuleType("sidecar.app.staging")

    def make_stage(cfg, login, request_id):
        captured["args"] = (cfg, login, request_id)
        return "STAGE"

    stmod.make_stage = make_stage
    monkeypatch.setitem(__import__("sys").modules, "sidecar.app.staging", stmod)
    login = NsLogin(api_user="u", api_pass="p")
    assert server._build_stage("rid-1", login) == "STAGE"
    assert captured["args"] == (server._CFG, login, "rid-1")


def test_build_stage_bytes_returns_pair(monkeypatch):
    """_build_stage_bytes returns a (stage_bytes, commit) pair."""
    captured = {}
    stmod = types.ModuleType("sidecar.app.staging")

    def make_stage_bytes(cfg, login, request_id):
        captured["args"] = (cfg, login, request_id)
        return ("WRITER", "COMMITTER")

    stmod.make_stage_bytes = make_stage_bytes
    monkeypatch.setitem(__import__("sys").modules, "sidecar.app.staging", stmod)
    login = NsLogin(api_user="u", api_pass="p")
    result = server._build_stage_bytes("rid-1", login)
    assert result == ("WRITER", "COMMITTER")
    assert captured["args"] == (server._CFG, login, "rid-1")


def test_nshttpconfig_repr_redacts_password():
    """NsHttpConfig repr must not reveal username or password (I-1 credential-safety guard)."""
    cfg = server.NsHttpConfig(base_url="http://ns", auth=("alice", "hunter2"))
    r = repr(cfg)
    assert "hunter2" not in r
    assert "alice" not in r
    assert "http://ns" in r  # base_url is safe to show
