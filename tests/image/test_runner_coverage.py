"""Image-internal tests for _nextseek_runner.py coverage.

Designed to run INSIDE dmac-assistant:poc at /host-tests/image/.
PYTHONPATH=/app/plugins/nextseek/bin must be set before pytest is invoked
so that coverage.py can correlate the module name _nextseek_runner with
the file at /app/plugins/nextseek/bin/_nextseek_runner.py.

DO NOT run this file on the host — it imports _nextseek_runner directly
and references /app/ paths that do not exist on the host.

Architecture: direct-import + monkeypatch. Every test calls runner.main()
in the same pytest process. This is the ONLY source of coverage data for
--cov-fail-under=95.

Coverage target: _nextseek_runner.py >= 95%
Empirical baseline: 43% with dry-run-only tests (orchestrator probe
2026-05-04 evening). This file must close the gap to >=95% via
monkeypatched non-dry-run dispatcher tests.

Production _nextseek_runner.py is UNCHANGED — no pragmas were added.
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

import pytest

# Direct import — this is what makes coverage.py see the module.
sys.path.insert(0, "/app/plugins/nextseek/bin")
import _nextseek_runner as runner  # noqa: E402

BASE_ENV = {
    "API_USER": "testuser",
    "API_PASS": "testpass",
    "NEXTSEEK_DRY_RUN": "1",
}


def _invoke(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    env_overrides: dict[str, str] | None = None,
    *,
    expect_exit: int = 0,
) -> tuple[str, str]:
    """Invoke runner.main() with the given argv and env."""
    env = {**os.environ, **BASE_ENV, **(env_overrides or {})}
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", *argv])
    for k, v in env.items():
        if v is not None:
            monkeypatch.setenv(k, v)
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)

    if expect_exit == 0:
        runner.main()
        return "", ""
    else:
        with pytest.raises(SystemExit) as exc_info:
            runner.main()
        assert exc_info.value.code == expect_exit
        return "", ""


# Section A: dry-run tests (8 dispatchers)

def test_dry_run_entity_dispatch(monkeypatch, capsys):
    _invoke(["--agent", "entity", "--query", "find LinVo samples"], monkeypatch)
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "sampletypes" in payload
    assert isinstance(payload["sampletypes"], list)


def test_dry_run_parse_dispatch(monkeypatch, capsys):
    _invoke(["--agent", "parse", "--query", "find LinVo samples"], monkeypatch)
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "mode" in payload


def test_dry_run_plan_dispatch(monkeypatch, capsys):
    _invoke(["--agent", "plan", "--query", "find samples"], monkeypatch)
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "plan" in payload
    assert isinstance(payload["plan"], list)


def test_dry_run_api_read_dispatch(monkeypatch, capsys):
    _invoke(
        ["--agent", "api-read", "--parser-plan", json.dumps({"endpoint": "/sample/", "method": "GET"})],
        monkeypatch,
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "endpoint" in payload
    assert "method" in payload
    assert "response" in payload


def test_dry_run_api_write_with_confirmed_write(monkeypatch, capsys):
    _invoke(
        ["--agent", "api-write",
         "--parser-plan", json.dumps({"endpoint": "/sample/", "method": "POST"}),
         "--confirmed-write"],
        monkeypatch,
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "endpoint" in payload
    assert "method" in payload


def test_dry_run_graph_dispatch(monkeypatch, capsys):
    _invoke(["--agent", "graph", "--query", "find samples"], monkeypatch)
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "cypher" in payload
    assert "result" in payload


def test_dry_run_report_dispatch(monkeypatch, capsys):
    _invoke(
        ["--agent", "report", "--mode", "samples", "--project", "TestProj"],
        monkeypatch,
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "summary" in payload
    assert "saved_files" in payload
    assert "rows" in payload


def test_dry_run_generate_submission_dispatch(monkeypatch, capsys):
    _invoke(
        ["--agent", "generate-submission", "--type", "GEO", "--uids", "uid1,uid2"],
        monkeypatch,
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "report" in payload
    assert "type" in payload


# Section B: non-dry-run dispatcher tests (8 dispatchers, monkeypatched agents)

def _patch_config_and_session(monkeypatch):
    monkeypatch.setattr(runner, "_load_config", lambda: None)
    monkeypatch.setattr(runner, "_make_session", lambda config: None)


def test_nondryrun_entity_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    fake_out = {"sampletypes": ["PAT"], "assays": [], "keywords": [], "projects": []}

    class FakeResult:
        def model_dump(self):
            return fake_out

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.entity_agent = lambda config, query: FakeResult()
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    _invoke(["--agent", "entity", "--query", "test"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["sampletypes"] == ["PAT"]


def test_nondryrun_parse_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types
    fake_entity_result = types.SimpleNamespace(mode="new_search", target_endpoint=None)
    fake_plan = types.SimpleNamespace(
        model_dump=lambda: {"mode": "new_search", "target_endpoint": None}
    )

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.parser_agent = lambda session, config, query, entity_out: fake_plan
    fake_chat_agents.entity_agent = lambda config, query: fake_entity_result
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    _invoke(["--agent", "parse", "--query", "test"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["mode"] == "new_search"


def test_nondryrun_plan_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types
    fake_plan = {"plan": ["step1"], "executed_read_steps": [], "context_engineer_outputs": [],
                 "evaluator": None, "skipped_steps": [], "recommended_next_actions": []}

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.entity_agent = lambda config, query: object()
    fake_chat_agents.multi_parser_agent = lambda session, config, query, entity_out: object()
    fake_chat_agents.planner_agent = lambda session, config, query, entity_out, multi: fake_plan
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    _invoke(["--agent", "plan", "--query", "test"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "step1" in payload["plan"]


def test_nondryrun_api_read_dispatch(monkeypatch, capsys, tmp_path):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    # Allowlist file containing the endpoint this test invokes.
    ep_file = tmp_path / "read_safe_endpoints.json"
    ep_file.write_text(json.dumps([{"endpoint": "/sample/", "methods": ["GET"]}]))
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(ep_file))

    class FakeApiPlan:
        endpoint = "/sample/"
        method = "GET"
        requestBody = None
        queryParameters = {}
        def model_dump(self): return {"endpoint": "/sample/", "method": "GET"}

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.api_agent_build_request = lambda config, plan_dict: FakeApiPlan()
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    fake_helpers = types.ModuleType("chat_nextseek.helpers")
    fake_helpers.tool_nextseek_api_request = lambda config, ep, method, **kw: {"results": []}
    fake_chat = types.ModuleType("chat_nextseek")
    fake_chat.helpers = fake_helpers
    monkeypatch.setitem(sys.modules, "chat_nextseek", fake_chat)
    monkeypatch.setitem(sys.modules, "chat_nextseek.helpers", fake_helpers)

    _invoke(
        ["--agent", "api-read", "--parser-plan", json.dumps({"endpoint": "/sample/", "method": "GET"})],
        monkeypatch,
        env_overrides={"NEXTSEEK_DRY_RUN": None},
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["endpoint"] == "/sample/"
    assert payload["method"] == "GET"


def test_nondryrun_api_write_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    class FakeApiPlan:
        endpoint = "/sample/"
        method = "POST"
        requestBody = {"name": "test"}
        queryParameters = {}
        def model_dump(self): return {"endpoint": "/sample/", "method": "POST"}

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.api_agent_build_request = lambda config, plan_dict: FakeApiPlan()
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    fake_helpers = types.ModuleType("chat_nextseek.helpers")
    fake_helpers.tool_nextseek_api_request = lambda config, ep, method, **kw: {"created": True}
    fake_chat = types.ModuleType("chat_nextseek")
    fake_chat.helpers = fake_helpers
    monkeypatch.setitem(sys.modules, "chat_nextseek", fake_chat)
    monkeypatch.setitem(sys.modules, "chat_nextseek.helpers", fake_helpers)

    _invoke(
        ["--agent", "api-write",
         "--parser-plan", json.dumps({"endpoint": "/sample/", "method": "POST"}),
         "--confirmed-write"],
        monkeypatch,
        env_overrides={"NEXTSEEK_DRY_RUN": None},
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["endpoint"] == "/sample/"
    assert payload["method"] == "POST"


def test_nondryrun_graph_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.entity_agent = lambda config, query: object()
    fake_chat_agents.graph_agent = lambda config, query, entity_out: {"cypher": "MATCH (n)", "result": [{"n": 1}]}
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    _invoke(["--agent", "graph", "--query", "test"], monkeypatch,
            env_overrides={"NEXTSEEK_DRY_RUN": None})
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert "cypher" in payload
    assert "result" in payload


def test_nondryrun_report_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    fake_helpers = types.ModuleType("chat_nextseek.helpers")
    fake_helpers.run_reporter_summary = lambda config, rp, log_dir: (
        [{"row": 1}], ["/tmp/nextseek/report.csv"], "Summary text"
    )
    fake_chat = types.ModuleType("chat_nextseek")
    fake_chat.helpers = fake_helpers
    monkeypatch.setitem(sys.modules, "chat_nextseek", fake_chat)
    monkeypatch.setitem(sys.modules, "chat_nextseek.helpers", fake_helpers)

    fake_schemas_chat = types.ModuleType("chat_nextseek.schemas.chat")
    fake_schemas_chat.ReporterPlan = lambda **kwargs: types.SimpleNamespace(**kwargs)
    fake_schemas = types.ModuleType("chat_nextseek.schemas")
    fake_schemas.chat = fake_schemas_chat
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas", fake_schemas)
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas.chat", fake_schemas_chat)

    _invoke(
        ["--agent", "report", "--mode", "samples", "--project", "TestProj"],
        monkeypatch,
        env_overrides={"NEXTSEEK_DRY_RUN": None},
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["summary"] == "Summary text"
    assert payload["rows"] == [{"row": 1}]


def test_nondryrun_generate_submission_dispatch(monkeypatch, capsys):
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)

    import types

    fake_out = {"report": "GEO submission text", "type": "GEO"}

    fake_chat_agents = types.ModuleType("chat_nextseek.agents")
    fake_chat_agents.report_writer_agent = lambda config, query, plan: fake_out
    monkeypatch.setitem(sys.modules, "chat_nextseek.agents", fake_chat_agents)

    fake_schemas_chat = types.ModuleType("chat_nextseek.schemas.chat")
    fake_schemas_chat.ReportWriterPlan = lambda **kwargs: types.SimpleNamespace(**kwargs)
    fake_schemas = types.ModuleType("chat_nextseek.schemas")
    fake_schemas.chat = fake_schemas_chat
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas", fake_schemas)
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas.chat", fake_schemas_chat)

    _invoke(
        ["--agent", "generate-submission", "--type", "GEO", "--uids", "uid1,uid2"],
        monkeypatch,
        env_overrides={"NEXTSEEK_DRY_RUN": None},
    )
    out, _ = capsys.readouterr()
    payload = json.loads(out.strip())
    assert payload["report"] == "GEO submission text"
    assert payload["type"] == "GEO"


# Section C: _load_read_safe_endpoints tests (covers lines 69-88)

def test_load_read_safe_endpoints_happy_path(monkeypatch, tmp_path):
    allowlist_data = [
        {"endpoint": "/sample/", "methods": ["GET", "POST"]},
        {"endpoint": "/experiment/", "methods": ["GET"]},
    ]
    ep_file = tmp_path / "read_safe_endpoints.json"
    ep_file.write_text(json.dumps(allowlist_data))
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(ep_file))

    result = runner._load_read_safe_endpoints()
    assert ("/sample/", "GET") in result
    assert ("/sample/", "POST") in result
    assert ("/experiment/", "GET") in result
    assert len(result) == 3


def test_load_read_safe_endpoints_missing_file(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "NEXTSEEK_READ_SAFE_ENDPOINTS_PATH",
        str(tmp_path / "nonexistent.json"),
    )
    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()
    assert exc_info.value.code == 6


def test_load_read_safe_endpoints_malformed_json(monkeypatch, tmp_path):
    ep_file = tmp_path / "bad.json"
    ep_file.write_text("{not valid json!!!")
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(ep_file))
    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()
    assert exc_info.value.code == 6


# Section D: _load_config ImportError test (covers lines 45-48)

def test_load_config_import_error(monkeypatch):
    """_load_config exits 2 (IMPORT_FAILED) when chat_nextseek.config is unimportable."""
    monkeypatch.setitem(sys.modules, "chat_nextseek.config", None)  # type: ignore[assignment]
    with pytest.raises(SystemExit) as exc_info:
        runner._load_config()
    assert exc_info.value.code == 2


# Section E: L2 write-blocked test (CRITICAL-3, covers lines 179-181)

def test_l2_write_blocked_without_confirmed_write(monkeypatch):
    """CRITICAL-3: api-write without --confirmed-write must exit 5 (WRITE_BLOCKED).

    Control flow note: in main(), `_load_config()` (line 286) executes BEFORE
    the dispatcher call (line 290) where the L2 check at line 179-181 lives.
    Without monkeypatching `_load_config` and `_make_session`, the
    `RuntimeError: GCP mode selected but GCP_API_KEY is not set` from
    `ChatConfig({})` would propagate uncaught (it is outside the try block at
    lines 289-296), masking the L2 exit-5 we want to assert. We therefore
    neutralise both helpers via `_patch_config_and_session(monkeypatch)` so
    main() reaches the dispatcher cleanly and the L2 check is the only thing
    that can trigger SystemExit. The dispatcher then exits 5 unconditionally
    regardless of dry-run state, which is the property under test.
    """
    _patch_config_and_session(monkeypatch)
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.setenv("API_USER", "testuser")
    monkeypatch.setenv("API_PASS", "testpass")
    monkeypatch.setattr(sys, "argv", [
        "_nextseek_runner", "--agent", "api-write",
        "--parser-plan", json.dumps({"endpoint": "/sample/", "method": "POST"}),
    ])
    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 5, (
        f"Expected exit 5 (WRITE_BLOCKED), got {exc_info.value.code}. "
        f"CRITICAL-3: Layer 2 check must fire unconditionally."
    )


# Section F: AGENT_FAILED catch-all test (covers lines 293-296)

def test_agent_failed_catch_all(monkeypatch):
    """main() except Exception branch exits 4 (AGENT_FAILED) when agent raises."""
    monkeypatch.setattr(sys, "argv", [
        "_nextseek_runner", "--agent", "entity", "--query", "test",
    ])
    monkeypatch.setenv("NEXTSEEK_DRY_RUN", "1")
    monkeypatch.setenv("API_USER", "testuser")
    monkeypatch.setenv("API_PASS", "testpass")

    def _raise_agent(*args, **kwargs):
        raise RuntimeError("simulated agent failure")

    monkeypatch.setattr(runner, "_dispatch_entity", _raise_agent)
    monkeypatch.setitem(runner._DISPATCH, "entity", _raise_agent)

    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 4


# Section G: _err and _dry_run unit tests

def test_err_helper_exits_with_code():
    with pytest.raises(SystemExit) as exc_info:
        runner._err("TEST_CODE", "test message", 7)
    assert exc_info.value.code == 7


def test_dry_run_true_when_env_set(monkeypatch):
    monkeypatch.setenv("NEXTSEEK_DRY_RUN", "1")
    assert runner._dry_run() is True


def test_dry_run_false_when_env_absent(monkeypatch):
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    assert runner._dry_run() is False
