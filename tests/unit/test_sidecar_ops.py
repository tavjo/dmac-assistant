"""Each of the 7 ops maps to the right portable.py call with the right args.

chat_nextseek is mocked via sys.modules so this runs on the 3.12 host (chat_nextseek
is image-only — feedback_chat_nextseek_host_image_split). We assert the dispatch
SHAPE (which portable fn, arg order), mirroring recon:runner §1j.
"""
import sys
import types

import pytest

from sidecar.app import ops


@pytest.fixture
def fake_portable(monkeypatch):
    calls = {}
    mod = types.ModuleType("chat_nextseek.portable")

    def mk(name):
        def fn(*a, **k):
            calls[name] = {"args": a, "kwargs": k}

            class _R:
                def model_dump(self):
                    return {"_op": name}

            return _R()

        return fn

    for n in ("entity_agent", "parser_agent", "multi_parser_agent", "planner_agent",
              "graph_agent", "report_writer_agent", "api_agent_build_request"):
        setattr(mod, n, mk(n))
    # helpers + reporter summary
    helpers = types.ModuleType("chat_nextseek.helpers")
    helpers.tool_nextseek_api_request = lambda *a, **k: {"ok": True}
    helpers.run_reporter_summary = lambda *a, **k: ({"rows": []}, {"f": "/p"}, {"summary": "s"})
    monkeypatch.setitem(sys.modules, "chat_nextseek.portable", mod)
    monkeypatch.setitem(sys.modules, "chat_nextseek.helpers", helpers)
    return calls


# A richer fake that also installs the `chat_nextseek` parent package and the
# `chat_nextseek.schemas.chat` module, needed by the api/report/submission ops
# (those handlers do `from chat_nextseek import helpers` and import ReporterPlan /
# ReportWriterPlan). `calls` records every portable invocation by name.
class _Plan:
    def __init__(self):
        self.endpoint = "/samples/"
        self.method = "get"
        self.requestBody = {"b": 1}
        self.queryParameters = {"q": 2}

    def model_dump(self):
        return {"endpoint": self.endpoint, "method": self.method}


@pytest.fixture
def fake_full(monkeypatch):
    calls = {}

    pkg = types.ModuleType("chat_nextseek")
    portable = types.ModuleType("chat_nextseek.portable")
    helpers = types.ModuleType("chat_nextseek.helpers")
    schemas = types.ModuleType("chat_nextseek.schemas")
    schemas_chat = types.ModuleType("chat_nextseek.schemas.chat")

    def mk(name, retval=None):
        def fn(*a, **k):
            calls[name] = {"args": a, "kwargs": k}
            return retval if retval is not None else _record_model(name)
        return fn

    def _record_model(name):
        class _R:
            def model_dump(self):
                return {"_op": name}
        return _R()

    portable.entity_agent = mk("entity_agent")
    portable.graph_agent = mk("graph_agent")
    portable.api_agent_build_request = mk("api_agent_build_request", retval=_Plan())
    portable.report_writer_agent = mk("report_writer_agent")

    def _api_req(*a, **k):
        calls["tool_nextseek_api_request"] = {"args": a, "kwargs": k}
        return {"ok": True}
    helpers.tool_nextseek_api_request = _api_req

    def _reporter(*a, **k):
        calls["run_reporter_summary"] = {"args": a, "kwargs": k}
        return ({"rows": []}, {"out.csv": "/p/out.csv"}, {"summary": "done"})
    helpers.run_reporter_summary = _reporter

    class _ReporterPlan:
        def __init__(self, **kw):
            calls["ReporterPlan"] = kw

    class _ReportWriterPlan:
        def __init__(self, **kw):
            calls["ReportWriterPlan"] = kw

    schemas_chat.ReporterPlan = _ReporterPlan
    schemas_chat.ReportWriterPlan = _ReportWriterPlan

    helpers_parent_attr = helpers
    pkg.helpers = helpers_parent_attr
    pkg.portable = portable
    pkg.schemas = schemas
    schemas.chat = schemas_chat

    monkeypatch.setitem(sys.modules, "chat_nextseek", pkg)
    monkeypatch.setitem(sys.modules, "chat_nextseek.portable", portable)
    monkeypatch.setitem(sys.modules, "chat_nextseek.helpers", helpers)
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas", schemas)
    monkeypatch.setitem(sys.modules, "chat_nextseek.schemas.chat", schemas_chat)
    return calls


# ---- spec example tests (verbatim) -----------------------------------------
def test_entity_op(fake_portable):
    cfg = object()
    out = ops.run_op("entity", {"query": "q"}, config=cfg, session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "entity_agent"
    assert fake_portable["entity_agent"]["args"][1] == "q"  # entity_agent(config, query)


def test_parse_op_takes_session_first(fake_portable):
    sess = object()
    ops.run_op("parse", {"query": "q"}, config=object(), session=sess,
               write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert fake_portable["parser_agent"]["args"][0] is sess  # parser_agent(session, config, ...)


def test_unknown_op_raises_validation(fake_portable):
    with pytest.raises(ops.OpValidationError):
        ops.run_op("query", {"query": "q"}, config=object(), session=None,
                   write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)  # query is not a sidecar op


# ---- additional coverage of the remaining handlers --------------------------
def test_entity_op_call_shape(fake_portable):
    cfg = object()
    ops.run_op("entity", {"query": "q"}, config=cfg, session=None,
               write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    # entity_agent(config, query) — recon:runner §1j
    assert fake_portable["entity_agent"]["args"] == (cfg, "q")


def test_parse_op_full_call_shape(fake_portable):
    cfg = object()
    sess = object()
    ops.run_op("parse", {"query": "q"}, config=cfg, session=sess,
               write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    # entity_agent(config, query) then parser_agent(session, config, query, entity_out)
    assert fake_portable["entity_agent"]["args"] == (cfg, "q")
    parse_args = fake_portable["parser_agent"]["args"]
    assert parse_args[0] is sess and parse_args[1] is cfg and parse_args[2] == "q"


def test_graph_op_call_shape(fake_portable):
    cfg = object()
    out = ops.run_op("graph", {"query": "q"}, config=cfg, session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "graph_agent"
    # entity_agent(config, query) then graph_agent(config, query, entity_out)
    assert fake_portable["entity_agent"]["args"] == (cfg, "q")
    g_args = fake_portable["graph_agent"]["args"]
    assert g_args[0] is cfg and g_args[1] == "q"


def test_api_read_op(fake_full):
    gate_calls = []

    def gate(*a):
        gate_calls.append(a)

    cfg = object()
    out = ops.run_op("api-read", {"parser_plan": '{"mode": "x"}'}, config=cfg, session=None,
                     write_gate=gate, stage=ops.NO_STAGE)
    # write_gate called BEFORE the request, with the resolved endpoint/method, confirmed=False
    assert gate_calls == [("api-read", "/samples/", "GET", False)]
    assert out["endpoint"] == "/samples/" and out["method"] == "GET"
    assert out["response"] == {"ok": True}
    assert out["api_plan"] == {"endpoint": "/samples/", "method": "get"}
    # api_agent_build_request(config, json.loads(parser_plan))
    assert fake_full["api_agent_build_request"]["args"][0] is cfg
    assert fake_full["api_agent_build_request"]["args"][1] == {"mode": "x"}


def test_api_write_op_passes_confirmed(fake_full):
    gate_calls = []

    def gate(*a):
        gate_calls.append(a)

    out = ops.run_op("api-write", {"parser_plan": '{"mode": "x"}', "confirmed_write": True},
                     config=object(), session=None, write_gate=gate, stage=ops.NO_STAGE)
    # write_gate("api-write", None, None, confirmed) BEFORE building/sending
    assert gate_calls == [("api-write", None, None, True)]
    assert out["endpoint"] == "/samples/" and out["method"] == "GET"
    assert out["response"] == {"ok": True}


def test_api_write_confirmed_defaults_false(fake_full):
    gate_calls = []

    def gate(*a):
        gate_calls.append(a)

    ops.run_op("api-write", {"parser_plan": '{"mode": "x"}'},
               config=object(), session=None, write_gate=gate, stage=ops.NO_STAGE)
    assert gate_calls == [("api-write", None, None, False)]


def test_report_op_samples_mode(fake_full):
    cfg = object()
    out = ops.run_op("report", {"mode": "samples", "project": "P1"},
                     config=cfg, session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["summary"] == {"summary": "done"}
    assert out["saved_files"] == {"out.csv": "/p/out.csv"}
    assert out["rows"] == {"rows": []}
    # ReporterPlan(project=..., reporter_mode="summary", summary_mode="samples")
    assert fake_full["ReporterPlan"] == {
        "project": "P1", "reporter_mode": "summary", "summary_mode": "samples",
    }
    assert fake_full["run_reporter_summary"]["args"][0] is cfg


def test_report_op_rppr_maps_summary_mode(fake_full):
    ops.run_op("report", {"mode": "rppr", "project": "P1"},
               config=object(), session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert fake_full["ReporterPlan"]["summary_mode"] == "RPPR"


def test_generate_submission_op(fake_full):
    cfg = object()
    out = ops.run_op("generate-submission",
                     {"type": "GEO", "uids": "u1, u2 ,, u3", "query": "make it"},
                     config=cfg, session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "report_writer_agent"
    # report_writer_agent(config, query or "", plan)
    assert fake_full["report_writer_agent"]["args"][0] is cfg
    assert fake_full["report_writer_agent"]["args"][1] == "make it"
    # ReportWriterPlan(report_type=type, reporter_context={"uids": [...]}); blanks dropped
    assert fake_full["ReportWriterPlan"] == {
        "report_type": "GEO", "reporter_context": {"uids": ["u1", "u2", "u3"]},
    }


def test_generate_submission_op_default_query(fake_full):
    ops.run_op("generate-submission", {"type": "SRA", "uids": "u1"},
               config=object(), session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    # query absent -> "" passed to report_writer_agent
    assert fake_full["report_writer_agent"]["args"][1] == ""


def test_dump_passthrough_for_plain_dict(monkeypatch):
    # _dump returns the object unchanged when it has no model_dump (else branch).
    mod = types.ModuleType("chat_nextseek.portable")
    mod.entity_agent = lambda *a, **k: {"plain": "dict"}
    monkeypatch.setitem(sys.modules, "chat_nextseek.portable", mod)
    out = ops.run_op("entity", {"query": "q"}, config=object(), session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out == {"plain": "dict"}


def test_allow_all_and_no_stage_defaults():
    assert ops.ALLOW_ALL("api-read", "/x", "GET", False) is None
    sentinel = {"k": "v"}
    assert ops.NO_STAGE("report", sentinel) is sentinel
