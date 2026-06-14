"""Image-internal tests for the THIN _nextseek_runner.py (T11 rewrite).

Designed to run INSIDE dmac-assistant:poc at /host-tests/image/.
PYTHONPATH=/app/plugins/nextseek/bin must be set before pytest is invoked
so that coverage.py can correlate the module name _nextseek_runner with
the file at /app/plugins/nextseek/bin/_nextseek_runner.py.

DO NOT run this file on the host — it imports _nextseek_runner directly
from the /app/ path that exists only in the image.

Architecture: direct-import + monkeypatch (T8's test_thin_runner_dispatch
pattern). The runner is a thin client: 7 ops go to the sidecar via
_sidecar_client.call_op, 2 ops (query/plan) ride the NExtSEEK assistant
viewset via _assistant_client.AssistantClient. NO chat_nextseek modules
are fabricated here — chat_nextseek is sidecar-only (U-11) and is NOT
importable in this image (see test_image_smoke.py).

This file is the ONLY source of coverage data for the binding
--cov=_nextseek_runner --cov-fail-under=95 gate
(tests/test_image_binding_gate.py::test_image_coverage_gate_passes).
"""
from __future__ import annotations

import json
import os
import sys

import pytest

# Direct import — this is what makes coverage.py see the module.
sys.path.insert(0, "/app/plugins/nextseek/bin")
import _nextseek_runner as runner  # noqa: E402
import _sidecar_client as sc  # noqa: E402
import _assistant_client as ac  # noqa: E402

BASE_ENV = {
    "API_USER": "testuser",
    "API_PASS": "testpass",
    "NEXTSEEK_URL": "https://ns.example",
    "NEXTSEEK_DRY_RUN": "1",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str | None] | None = None) -> None:
    env: dict[str, str | None] = {**BASE_ENV, **(overrides or {})}
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _invoke(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    env_overrides: dict[str, str | None] | None = None,
    *,
    expect_exit: int = 0,
) -> None:
    """Invoke runner.main() with the given argv and env."""
    _set_env(monkeypatch, env_overrides)
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", *argv])
    if expect_exit == 0:
        runner.main()
    else:
        with pytest.raises(SystemExit) as exc_info:
            runner.main()
        assert exc_info.value.code == expect_exit, (
            f"expected exit {expect_exit}, got {exc_info.value.code}"
        )


# ---------------------------------------------------------------------------
# Section A: dry-run dispatch — all 9 ops emit minimal typed JSON, exit 0
# ---------------------------------------------------------------------------

_DRY_RUN_CASES = [
    (["--agent", "query", "--query", "find samples"], "reply"),
    (["--agent", "query", "--query", "find samples", "--planner"], "reply"),
    (["--agent", "entity", "--query", "find samples"], "sampletypes"),
    (["--agent", "parse", "--query", "find samples"], "mode"),
    (["--agent", "plan", "--query", "find samples"], "plan"),
    (["--agent", "api-read", "--parser-plan", '{"endpoint": "/x/"}'], "endpoint"),
    (["--agent", "api-write", "--parser-plan", '{"endpoint": "/x/"}',
      "--confirmed-write"], "endpoint"),
    (["--agent", "graph", "--query", "lineage of S1"], "cypher"),
    (["--agent", "report", "--mode", "samples", "--project", "P"], "summary"),
    (["--agent", "generate-submission", "--type", "GEO", "--uids", "u1,u2"],
     "report"),
]


@pytest.mark.parametrize("argv,expected_key", _DRY_RUN_CASES,
                         ids=["-".join(c[0][1:3]) for c in _DRY_RUN_CASES])
def test_dry_run_dispatch_emits_typed_json(argv, expected_key, monkeypatch, capsys):
    _invoke(argv, monkeypatch)
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert expected_key in payload, (
        f"dry-run payload for {argv!r} missing {expected_key!r}: {payload!r}"
    )


# ---------------------------------------------------------------------------
# Section B: local validation — exits before any sidecar/viewset traffic
# ---------------------------------------------------------------------------

def test_api_read_rejects_confirmed_write_exit3(monkeypatch, capsys):
    _invoke(["--agent", "api-read", "--parser-plan", "{}", "--confirmed-write"],
            monkeypatch, expect_exit=3)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "VALIDATION"


def test_api_write_without_confirm_exit5(monkeypatch, capsys):
    """L2 advisory write gate fires unconditionally (even in dry-run)."""
    _invoke(["--agent", "api-write", "--parser-plan", "{}"],
            monkeypatch, expect_exit=5)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "WRITE_BLOCKED"


def test_report_bad_mode_exit3(monkeypatch, capsys):
    _invoke(["--agent", "report", "--mode", "bogus", "--project", "P"],
            monkeypatch, expect_exit=3)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "VALIDATION"


def test_report_missing_project_exit3(monkeypatch):
    _invoke(["--agent", "report", "--mode", "samples"],
            monkeypatch, expect_exit=3)


def test_generate_submission_bad_type_exit3(monkeypatch):
    _invoke(["--agent", "generate-submission", "--type", "NOPE", "--uids", "u"],
            monkeypatch, expect_exit=3)


def test_generate_submission_missing_uids_exit3(monkeypatch):
    _invoke(["--agent", "generate-submission", "--type", "GEO"],
            monkeypatch, expect_exit=3)


# ---------------------------------------------------------------------------
# Section C: CONFIG_MISSING guard (Important-2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["API_USER", "API_PASS"])
def test_missing_cred_exits_config_missing(missing, monkeypatch, capsys):
    _invoke(["--agent", "entity", "--query", "x"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None, missing: None},
            expect_exit=2)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "CONFIG_MISSING"


# ---------------------------------------------------------------------------
# Section D: sidecar dispatch (injected fake call_op — no network)
# ---------------------------------------------------------------------------

_SIDECAR_CASES = [
    ("entity", ["--query", "myq"], {"query": "myq"}),
    ("parse", ["--query", "myq"], {"query": "myq"}),
    ("graph", ["--query", "myq"], {"query": "myq"}),
    ("api-read", ["--parser-plan", '{"x":1}'], {"parser_plan": '{"x":1}'}),
    ("api-write", ["--parser-plan", '{"x":1}', "--confirmed-write"],
     {"parser_plan": '{"x":1}', "confirmed_write": True}),
    ("report", ["--mode", "samples", "--project", "MyProj"],
     {"mode": "samples", "project": "MyProj"}),
    ("generate-submission",
     ["--type", "GEO", "--uids", "u1,u2", "--query", "geoq"],
     {"type": "GEO", "uids": "u1,u2", "query": "geoq"}),
]


@pytest.mark.parametrize("op,argv_extra,expected_args", _SIDECAR_CASES,
                         ids=[c[0] for c in _SIDECAR_CASES])
def test_sidecar_op_calls_call_op_with_mapped_args(
    op, argv_extra, expected_args, monkeypatch, capsys
):
    captured: dict = {}

    def fake_call_op(captured_op, captured_args, **kwargs):
        captured["op"] = captured_op
        captured["args"] = captured_args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(sc, "call_op", fake_call_op)
    _invoke(["--agent", op, *argv_extra], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    assert json.loads(out.strip()) == {"ok": True}
    assert captured["op"] == op
    assert captured["args"] == expected_args
    assert captured["kwargs"]["ns_login"] == ("testuser", "testpass")


@pytest.mark.parametrize("code,exit_code", [
    ("WRITE_BLOCKED", 5),
    ("TRANSPORT_ERROR", 7),
])
def test_sidecar_call_error_propagates_exit_code(code, exit_code, monkeypatch, capsys):
    def fake_call_op(op, args, **kwargs):
        raise sc.SidecarCallError(code, "boom")

    monkeypatch.setattr(sc, "call_op", fake_call_op)
    _invoke(["--agent", "entity", "--query", "x"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None}, expect_exit=exit_code)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == code


# ---------------------------------------------------------------------------
# Section E: viewset path (query/plan — injected fake AssistantClient)
# ---------------------------------------------------------------------------

class _FakeClientFactory:
    """Builds an AssistantClient stand-in whose run_query returns or raises."""

    def __init__(self, terminal=None, exc=None):
        self.terminal = terminal
        self.exc = exc
        self.captured: dict = {}

    def __call__(self, **kwargs):
        self.captured["init"] = kwargs
        factory = self

        class _Client:
            def run_query(self, query, *, mode, **kw):
                factory.captured["query"] = query
                factory.captured["mode"] = mode
                if factory.exc is not None:
                    raise factory.exc
                return factory.terminal, []

        return _Client()


def test_query_viewset_success_emits_shaped_reply(monkeypatch, capsys):
    factory = _FakeClientFactory(
        terminal={"reply": "3 samples", "debug": {"x": 1}, "bundle_id": 7},
    )
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "find samples"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload == {"reply": "3 samples", "debug": {"x": 1}, "bundle_id": 7}
    assert factory.captured["mode"] == "standard"
    assert factory.captured["init"]["auth"] == ("testuser", "testpass")


def test_query_planner_flag_selects_plan_mode(monkeypatch, capsys):
    factory = _FakeClientFactory(terminal={"reply": "ok"})
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "q", "--planner"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    capsys.readouterr()
    assert factory.captured["mode"] == "plan"


def test_plan_op_rides_viewset_plan_mode(monkeypatch, capsys):
    factory = _FakeClientFactory(terminal={"reply": "planned"})
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "plan", "--query", "q"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    capsys.readouterr()
    assert factory.captured["mode"] == "plan"


def test_viewset_error_terminal_maps_to_agent_failed_exit4(monkeypatch, capsys):
    factory = _FakeClientFactory(terminal={"__error__": "agent blew up"})
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "q"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None}, expect_exit=4)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "AGENT_FAILED"


def test_viewset_401_maps_to_auth_failed_exit8(monkeypatch, capsys):
    import httpx

    class _Resp:
        status_code = 401

    factory = _FakeClientFactory(
        exc=httpx.HTTPStatusError("401", request=None, response=_Resp()),
    )
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "q"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None}, expect_exit=8)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "AUTH_FAILED"


def test_viewset_http_500_maps_to_agent_failed_exit4(monkeypatch, capsys):
    import httpx

    class _Resp:
        status_code = 500

    factory = _FakeClientFactory(
        exc=httpx.HTTPStatusError("500", request=None, response=_Resp()),
    )
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "q"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None}, expect_exit=4)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "AGENT_FAILED"


def test_viewset_transport_error_exit7(monkeypatch, capsys):
    import httpx

    factory = _FakeClientFactory(exc=httpx.ConnectError("refused"))
    monkeypatch.setattr(ac, "AssistantClient", factory)
    _invoke(["--agent", "query", "--query", "q"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None}, expect_exit=7)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "TRANSPORT_ERROR"


# ---------------------------------------------------------------------------
# Section F: AGENT_FAILED catch-all in main()
# ---------------------------------------------------------------------------

def test_agent_failed_catch_all_exit4(monkeypatch, capsys):
    def _boom(args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(runner._DISPATCH, "entity", _boom)
    _invoke(["--agent", "entity", "--query", "x"], monkeypatch, expect_exit=4)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err["error"]["code"] == "AGENT_FAILED"
    assert "RuntimeError" in err["error"]["message"]
    assert "kaboom" in err["error"]["message"]


# ---------------------------------------------------------------------------
# Section G: helper unit tests
# ---------------------------------------------------------------------------

def test_err_helper_exits_with_code(capsys):
    with pytest.raises(SystemExit) as exc_info:
        runner._err("TEST_CODE", "test message", 7)
    assert exc_info.value.code == 7
    err = json.loads(capsys.readouterr().err.strip())
    assert err == {"error": {"code": "TEST_CODE", "message": "test message"}}


def test_dry_run_true_when_env_set(monkeypatch):
    monkeypatch.setenv("NEXTSEEK_DRY_RUN", "1")
    assert runner._dry_run() is True


def test_dry_run_false_when_env_absent(monkeypatch):
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    assert runner._dry_run() is False


def test_sanitize_env_quotes_strips_matching_outer_quotes(monkeypatch):
    monkeypatch.setenv("T11_DQ", '"quoted"')
    monkeypatch.setenv("T11_SQ", "'quoted'")
    monkeypatch.setenv("T11_MIXED", "\"unbalanced'")
    monkeypatch.setenv("T11_PLAIN", "plain")
    runner._sanitize_env_quotes()
    assert os.environ["T11_DQ"] == "quoted"
    assert os.environ["T11_SQ"] == "quoted"
    assert os.environ["T11_MIXED"] == "\"unbalanced'"  # mismatched: untouched
    assert os.environ["T11_PLAIN"] == "plain"


def test_api_user_pass_read_from_env(monkeypatch):
    monkeypatch.setenv("API_USER", "u1")
    monkeypatch.setenv("API_PASS", "p1")
    assert runner._api_user() == "u1"
    assert runner._api_pass() == "p1"
