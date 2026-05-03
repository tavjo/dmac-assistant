"""Plan B · T2 · B2.2b: per-dispatcher monkeypatch tests for _nextseek_runner."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Skip cleanly if chat_nextseek is not installed in the test env (instead of
# failing with cryptic ModuleNotFoundError inside test bodies). Phase 4 review
# CRITICAL-2.
pytest.importorskip("chat_nextseek")

RUNNER_PATH = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def _load_runner():
    """Load _nextseek_runner.py as a module (it's a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_nextseek_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nextseek_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner():
    return _load_runner()


def test_dispatch_entity_calls_entity_agent_with_config_and_query(runner, monkeypatch):
    """entity_agent must be called with (config, query) in that order."""
    fake_entity_agent = MagicMock(return_value=MagicMock(model_dump=lambda: {"sampletypes": []}))
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_entity(args, config, session)

    fake_entity_agent.assert_called_once()
    call_args, call_kwargs = fake_entity_agent.call_args
    assert call_args[0] is config, f"first positional arg should be config, got {call_args[0]!r}"
    assert call_args[1] == "find samples", f"second positional arg should be query, got {call_args[1]!r}"
    assert result == {"sampletypes": []}


def test_dispatch_parse_calls_parser_agent_with_session_config_query_entity(runner, monkeypatch):
    """parser_agent must be called with (session, config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_parser_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"mode": "new_search"})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "parser_agent", fake_parser_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_parse(args, config, session)

    fake_entity_agent.assert_called_once()
    ent_args, _ = fake_entity_agent.call_args
    assert ent_args[0] is config
    assert ent_args[1] == "find samples"

    fake_parser_agent.assert_called_once()
    p_args, _ = fake_parser_agent.call_args
    assert p_args[0] is session, f"parser_agent arg0 should be session, got {p_args[0]!r}"
    assert p_args[1] is config, f"parser_agent arg1 should be config, got {p_args[1]!r}"
    assert p_args[2] == "find samples", f"parser_agent arg2 should be query, got {p_args[2]!r}"
    assert p_args[3] is fake_entity_out, f"parser_agent arg3 should be entity_out, got {p_args[3]!r}"
    assert result == {"mode": "new_search"}


def test_dispatch_plan_calls_planner_agent_with_full_positional_chain(runner, monkeypatch):
    """planner_agent must be called with (session, config, query, entity_out, multi)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_multi = MagicMock(name="multi_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_multi_parser_agent = MagicMock(return_value=fake_multi)
    fake_planner_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"plan": []})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "multi_parser_agent", fake_multi_parser_agent)
    monkeypatch.setattr(agents_mod, "planner_agent", fake_planner_agent)

    args = argparse.Namespace(query="find samples then lineage")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_plan(args, config, session)

    fake_multi_parser_agent.assert_called_once()
    mp_args, _ = fake_multi_parser_agent.call_args
    assert mp_args[0] is session
    assert mp_args[1] is config
    assert mp_args[2] == "find samples then lineage"
    assert mp_args[3] is fake_entity_out

    fake_planner_agent.assert_called_once()
    pl_args, _ = fake_planner_agent.call_args
    assert pl_args[0] is session, f"planner_agent arg0 should be session, got {pl_args[0]!r}"
    assert pl_args[1] is config, f"planner_agent arg1 should be config, got {pl_args[1]!r}"
    assert pl_args[2] == "find samples then lineage"
    assert pl_args[3] is fake_entity_out, f"planner_agent arg3 should be entity_out"
    assert pl_args[4] is fake_multi, f"planner_agent arg4 should be multi, got {pl_args[4]!r}"
    assert result == {"plan": []}


def test_dispatch_api_read_calls_helpers_tool_nextseek_api_request(runner, monkeypatch, tmp_path):
    """api-read: build_request → allowlist check → helpers.tool_nextseek_api_request."""
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "GET"
    fake_api_plan.requestBody = None
    fake_api_plan.queryParameters = {"project": "X"}
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "GET"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"results": []})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)
    monkeypatch.setattr(
        runner, "_load_read_safe_endpoints",
        lambda: {("/samples/", "GET")},
    )

    args = argparse.Namespace(
        parser_plan='{"mode": "new_search"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_read(args, config, session)

    fake_build_request.assert_called_once()
    br_args, _ = fake_build_request.call_args
    assert br_args[0] is config, f"api_agent_build_request arg0 should be config"
    assert br_args[1] == {"mode": "new_search"}, f"arg1 should be parsed plan dict"

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config, f"tool_nextseek_api_request arg0 should be config"
    assert tr_args[1] == "/samples/", f"arg1 should be endpoint"
    assert tr_args[2] == "GET", f"arg2 should be method"
    assert tr_kwargs.get("requestBody") is None
    assert tr_kwargs.get("queryParameters") == {"project": "X"}
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "GET"
    assert result["response"] == {"results": []}


def test_dispatch_api_write_with_confirmed_write_calls_helpers_tool_nextseek_api_request(
    runner, monkeypatch
):
    """api-write with --confirmed-write: passes through to helpers.tool_nextseek_api_request."""
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "POST"
    fake_api_plan.requestBody = {"name": "S1"}
    fake_api_plan.queryParameters = None
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "POST"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"created": True})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)

    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=True,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_write(args, config, session)

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config
    assert tr_args[1] == "/samples/"
    assert tr_args[2] == "POST"
    assert tr_kwargs.get("requestBody") == {"name": "S1"}
    assert tr_kwargs.get("queryParameters") is None
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "POST"


def test_dispatch_api_write_without_confirmed_write_exits_5(runner, monkeypatch):
    """api-write without --confirmed-write must SystemExit with code 5 (Layer-2 block)."""
    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    with pytest.raises(SystemExit) as exc_info:
        runner._dispatch_api_write(args, config, session)
    assert exc_info.value.code == 5, f"expected exit 5 (WRITE_BLOCKED), got {exc_info.value.code}"


def test_dispatch_graph_calls_graph_agent_with_config_query_entity(runner, monkeypatch):
    """graph_agent must be called with (config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_graph_agent = MagicMock(return_value={"cypher": "MATCH (n) RETURN n", "result": []})
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "graph_agent", fake_graph_agent)

    args = argparse.Namespace(query="lineage of S1")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_graph(args, config, session)

    fake_graph_agent.assert_called_once()
    g_args, _ = fake_graph_agent.call_args
    assert g_args[0] is config, f"graph_agent arg0 should be config"
    assert g_args[1] == "lineage of S1", f"graph_agent arg1 should be query"
    assert g_args[2] is fake_entity_out, f"graph_agent arg2 should be entity_out"
    assert result == {"cypher": "MATCH (n) RETURN n", "result": []}


def test_dispatch_report_calls_run_reporter_summary_with_reporter_plan(runner, monkeypatch):
    """run_reporter_summary must be called with (config, ReporterPlan, log_dir)."""
    fake_run_reporter = MagicMock(return_value=([{"row": 1}], ["/tmp/out.csv"], "summary text"))
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "run_reporter_summary", fake_run_reporter)
    monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")

    args = argparse.Namespace(mode="samples", project="ProjectA", query=None)
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_report(args, config, session)

    fake_run_reporter.assert_called_once()
    r_args, _ = fake_run_reporter.call_args
    assert r_args[0] is config, f"run_reporter_summary arg0 should be config"
    rp = r_args[1]
    assert rp.project == "ProjectA"
    assert rp.summary_mode == "samples", f"summary_mode should be 'samples', got {rp.summary_mode!r}"
    assert r_args[2] == "/tmp/nextseek", f"arg2 should be log_dir"
    assert result["summary"] == "summary text"
    assert result["saved_files"] == ["/tmp/out.csv"]


def test_dispatch_generate_submission_calls_report_writer_agent_with_plan(runner, monkeypatch):
    """report_writer_agent must be called with (config, query_str, ReportWriterPlan)."""
    fake_report = MagicMock()
    fake_report.model_dump = lambda: {"report": "text", "type": "GEO"}
    fake_writer = MagicMock(return_value=fake_report)
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "report_writer_agent", fake_writer)

    args = argparse.Namespace(type="GEO", uids="S1,S2", query="generate GEO")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_generate_submission(args, config, session)

    fake_writer.assert_called_once()
    w_args, _ = fake_writer.call_args
    assert w_args[0] is config, f"report_writer_agent arg0 should be config"
    assert w_args[1] == "generate GEO", f"arg1 should be query string"
    plan = w_args[2]
    assert plan.report_type == "GEO", f"report_type should be 'GEO', got {plan.report_type!r}"
    assert plan.reporter_context == {"uids": ["S1", "S2"]}
    assert result == {"report": "text", "type": "GEO"}


# ---------- amendment 2026-05-01: cover the previously-excepted branches ----

def test_load_config_emits_import_failed_when_chat_nextseek_unimportable(
    runner, monkeypatch, capsys
):
    """_load_config must exit 2 with IMPORT_FAILED when chat_nextseek.config is unimportable.

    Strategy: inject `None` into sys.modules['chat_nextseek.config'] — Python's
    import machinery treats that as a previously-failed import and raises a
    plain `ImportError` ("import of chat_nextseek.config halted; use of None
    is not allowed"), NOT a `ModuleNotFoundError`. The runner's
    `except ImportError as exc:` catches it because ImportError is the parent
    class either way.
    """
    import json as _json
    monkeypatch.setitem(sys.modules, "chat_nextseek.config", None)

    with pytest.raises(SystemExit) as exc_info:
        runner._load_config()

    assert exc_info.value.code == 2, f"expected exit 2 (CONFIG_MISSING/IMPORT_FAILED), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "IMPORT_FAILED"
    assert "chat_nextseek not importable" in payload["error"]["message"]


def test_load_read_safe_endpoints_emits_config_error_on_open_oserror(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when open() raises OSError.

    Strategy: point the path env var at an existing file (so the os.path.exists
    pre-check passes), then monkeypatch builtins.open to raise OSError when
    invoked on that path — this exercises the OSError branch of the try/except
    around `open(path)`/`json.load(fh)`.
    """
    import builtins
    import json as _json

    fake_path = tmp_path / "read_safe_endpoints.json"
    fake_path.write_text("[]")  # exists, but we'll force open to fail
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(fake_path))

    real_open = builtins.open

    def _raising_open(file, *args, **kwargs):
        if str(file) == str(fake_path):
            raise OSError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _raising_open)

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "OSError" in payload["error"]["message"] or "Permission denied" in payload["error"]["message"]


def test_main_wraps_unexpected_dispatcher_exception_as_agent_failed(
    runner, monkeypatch, capsys
):
    """main()'s broad except clause must convert non-SystemExit dispatcher errors
    to exit code 4 with an AGENT_FAILED payload.

    Strategy: enable NEXTSEEK_DRY_RUN so main() skips _load_config/_make_session,
    then monkeypatch the entity dispatcher in _DISPATCH to raise RuntimeError.
    Set sys.argv so argparse parses cleanly.
    """
    import json as _json

    monkeypatch.setenv("NEXTSEEK_DRY_RUN", "1")

    def _boom(args, config, session):
        raise RuntimeError("kaboom")

    # Replace the entity dispatcher in the module-level dispatch table.
    monkeypatch.setitem(runner._DISPATCH, "entity", _boom)
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner.py", "--agent", "entity", "--query", "x"])

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 4, f"expected exit 4 (AGENT_FAILED), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "AGENT_FAILED"
    assert "RuntimeError" in payload["error"]["message"]
    assert "kaboom" in payload["error"]["message"]


# ----- Phase 4 review CRITICAL-1 + HIGH-1: cover the real _load_read_safe_endpoints
# implementation and the _dispatch_report RPPR remap branch.

def test_load_read_safe_endpoints_happy_path_returns_endpoint_method_set(
    runner, monkeypatch, tmp_path
):
    """_load_read_safe_endpoints must parse a populated JSON file into a set of
    (endpoint, METHOD) tuples, exercising the json.load call, the for-loop
    body, and the allowlist.add line — all uncovered without this test.
    """
    fake_path = tmp_path / "read_safe_endpoints.json"
    fake_path.write_text(
        '[{"endpoint": "/samples/", "methods": ["GET", "post"]},'
        ' {"endpoint": "/projects/", "methods": ["GET"]}]'
    )
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(fake_path))

    allowlist = runner._load_read_safe_endpoints()

    assert allowlist == {
        ("/samples/", "GET"),
        ("/samples/", "POST"),  # method must be upper-cased
        ("/projects/", "GET"),
    }


def test_load_read_safe_endpoints_emits_config_error_when_file_missing(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when the path does
    not exist, exercising the os.path.exists → _err missing-file branch.
    """
    import json as _json

    missing_path = tmp_path / "does-not-exist.json"
    assert not missing_path.exists()  # sanity
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(missing_path))

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "missing" in payload["error"]["message"].lower()
    assert str(missing_path) in payload["error"]["message"]


def test_load_read_safe_endpoints_emits_config_error_on_malformed_json(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when the file is
    present but contains malformed JSON, exercising the json.JSONDecodeError
    arm of the `except (OSError, json.JSONDecodeError)` clause that the OSError
    test at line 493 leaves uncovered. Phase 4 re-review residual from
    CRITICAL-1.
    """
    import json as _json

    bad_path = tmp_path / "read_safe_endpoints.json"
    bad_path.write_text("{this is not valid json")  # malformed
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(bad_path))

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "JSONDecodeError" in payload["error"]["message"]


def test_dispatch_report_with_rppr_mode_remaps_summary_mode_to_uppercase(
    runner, monkeypatch
):
    """_dispatch_report must remap args.mode='rppr' → ReporterPlan.summary_mode='RPPR'.

    The base report test only exercises args.mode='samples' (else-branch of the
    ternary at runner line 806). This test covers the true-branch of that
    ternary — Phase 4 review HIGH-1.
    """
    fake_run_reporter = MagicMock(return_value=([{"row": 1}], ["/tmp/out.csv"], "summary"))
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "run_reporter_summary", fake_run_reporter)
    monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")

    args = argparse.Namespace(mode="rppr", project="ProjectA", query=None)
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    runner._dispatch_report(args, config, session)

    fake_run_reporter.assert_called_once()
    r_args, _ = fake_run_reporter.call_args
    rp = r_args[1]
    assert rp.summary_mode == "RPPR", f"summary_mode should remap 'rppr' → 'RPPR', got {rp.summary_mode!r}"
    assert rp.project == "ProjectA"
