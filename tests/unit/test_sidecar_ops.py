"""Each of the 7 ops dispatches to ns_client.call_op (HTTP) with the right body + auth.
For report/generate-submission: follows the download block, stages bytes, and commits
the .complete marker exactly once after the loop (F-T16-2-B).
"""
import pytest
from sidecar.app import ops


@pytest.fixture
def fake_client(monkeypatch):
    calls = {}

    def call_op(op, body, *, base_url, auth):
        calls[op] = {"body": body, "base_url": base_url, "auth": auth}
        if op == "report":
            return {"op": op, "result": {"summary": {}, "saved_files": {"published_report": "/srv/p.json"}, "rows": {}},
                    "download": {"session_id": "11111111-1111-4111-8111-111111111111", "bundle_id": 1,
                                 "artifacts": [{"key": "published_report", "url": "/dl/published_report/"}]}}
        if op == "generate-submission":
            return {"op": op, "result": {"report_writer_output": {"report_type": "GEO"}},
                    "download": {"session_id": "22222222-2222-4222-8222-222222222222", "bundle_id": 2,
                                 "artifacts": [{"key": "all_tables", "url": "/dl/all_tables/"}]}}
        return {"op": op, "result": {"_op": op}}

    fetched = {}

    def fetch_artifact(url, *, base_url, auth):
        fetched[url] = True
        return b"BYTES"

    monkeypatch.setattr(ops.ns_client, "call_op", call_op)
    monkeypatch.setattr(ops.ns_client, "fetch_artifact", fetch_artifact)
    return calls, fetched


class _Cfg:
    base_url = "http://ns"
    auth = ("u", "p")


def test_entity_calls_http(fake_client):
    calls, _ = fake_client
    out = ops.run_op("entity", {"query": "q"}, config=_Cfg(), session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "entity"
    assert calls["entity"]["body"] == {"query": "q"} and calls["entity"]["auth"] == ("u", "p")


def test_parse_calls_http(fake_client):
    calls, _ = fake_client
    out = ops.run_op("parse", {"query": "q"}, config=_Cfg(), session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "parse"
    assert calls["parse"]["body"] == {"query": "q"}


def test_graph_calls_http(fake_client):
    calls, _ = fake_client
    out = ops.run_op("graph", {"query": "q"}, config=_Cfg(), session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "graph"
    assert calls["graph"]["body"] == {"query": "q"}


def test_api_read_calls_http(fake_client):
    calls, _ = fake_client
    out = ops.run_op("api-read", {"parser_plan": '{"mode": "x"}'}, config=_Cfg(), session=None,
                     write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "api-read"
    assert calls["api-read"]["body"] == {"parser_plan": '{"mode": "x"}'}


def test_api_write_unconfirmed_blocks_before_http(fake_client):
    calls, _ = fake_client
    from sidecar.app.write_gate import build_gate
    gate = build_gate()  # real confirmed_write pre-check gate
    with pytest.raises(ops.WriteBlockedError):
        ops.run_op("api-write", {"parser_plan": "{}", "confirmed_write": False},
                   config=_Cfg(), session=None, write_gate=gate, stage=ops.NO_STAGE)
    assert "api-write" not in calls  # never reached the HTTP client


def test_api_write_confirmed_calls_http(fake_client):
    calls, _ = fake_client
    out = ops.run_op("api-write", {"parser_plan": '{"mode": "x"}', "confirmed_write": True},
                     config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert out["_op"] == "api-write"
    assert calls["api-write"]["body"]["confirmed_write"] is True


def test_report_downloads_and_stages(fake_client):
    calls, fetched = fake_client
    staged, commits = {}, []

    def stage_bytes(op, key, data):
        staged[key] = f"/staging/{op}/{key}"
        return staged[key]

    def commit_bytes():
        commits.append(1)  # marker committer (F-T16-2-B)

    out = ops.run_op("report", {"mode": "published", "project": "Published Data"},
                     config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
                     stage=ops.NO_STAGE, stage_bytes=stage_bytes, commit_bytes=commit_bytes)
    assert "/dl/published_report/" in fetched
    assert out["saved_files"]["published_report"] == "/staging/report/published_report"
    assert commits == [1]  # marker committed exactly once after the loop


def test_generate_submission_downloads_and_stages(fake_client):
    calls, fetched = fake_client
    staged, commits = {}, []

    def stage_bytes(op, key, data):
        staged[key] = f"/staging/{op}/{key}"
        return staged[key]

    def commit_bytes():
        commits.append(1)

    out = ops.run_op("generate-submission", {"type": "GEO", "uids": "UID1"},
                     config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
                     stage=ops.NO_STAGE, stage_bytes=stage_bytes, commit_bytes=commit_bytes)
    assert "/dl/all_tables/" in fetched
    assert out["staged_files"]["all_tables"] == "/staging/generate-submission/all_tables"
    assert commits == [1]


def test_report_multi_artifact_marker_written_once(monkeypatch):
    def call_op(op, body, *, base_url, auth):
        return {"op": op, "result": {"summary": {}, "saved_files": {}, "rows": {}},
                "download": {"session_id": "44444444-4444-4444-8444-444444444444", "bundle_id": 4,
                             "artifacts": [{"key": "merged_report", "url": "/dl/merged_report/"},
                                           {"key": "geo_seq_workbooks", "url": "/dl/geo_seq_workbooks/"}]}}

    def fetch_artifact(url, *, base_url, auth):
        return b"BYTES"

    monkeypatch.setattr(ops.ns_client, "call_op", call_op)
    monkeypatch.setattr(ops.ns_client, "fetch_artifact", fetch_artifact)
    order = []

    def stage_bytes(op, key, data):
        order.append(("stage", key))
        return f"/staging/{op}/{key}"

    def commit_bytes():
        order.append(("commit", None))

    out = ops.run_op("report", {"mode": "published", "project": "Published Data"},
                     config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
                     stage=ops.NO_STAGE, stage_bytes=stage_bytes, commit_bytes=commit_bytes)
    assert out["saved_files"]["merged_report"] == "/staging/report/merged_report"
    assert out["saved_files"]["geo_seq_workbooks"] == "/staging/report/geo_seq_workbooks"
    assert order.count(("commit", None)) == 1
    assert order[-1] == ("commit", None)
    assert order[:2] == [("stage", "merged_report"), ("stage", "geo_seq_workbooks")]


def test_unknown_op_raises_validation(fake_client):
    with pytest.raises(ops.OpValidationError):
        ops.run_op("query", {"query": "q"}, config=_Cfg(), session=None,
                   write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)


def test_allow_all_and_no_stage_defaults():
    assert ops.ALLOW_ALL("api-read", "/x", "GET", False) is None
    sentinel = {"k": "v"}
    assert ops.NO_STAGE("report", sentinel) is sentinel


def test_no_stage_bytes_default_writes_temp_no_marker(monkeypatch):
    """NO_STAGE_BYTES sentinel writes bytes to a temp path and returns a path string."""
    # NO_STAGE_BYTES should write bytes and return a path, not raise
    result = ops.NO_STAGE_BYTES("report", "my_key", b"test data")
    assert isinstance(result, str)
    # The path should be a valid string (temp path)
    assert len(result) > 0


def test_no_commit_is_noop():
    """NO_COMMIT sentinel is a no-op callable."""
    result = ops.NO_COMMIT()
    assert result is None


def test_api_write_invalid_parser_plan_raises_op_validation(fake_client):
    with pytest.raises(ops.OpValidationError):
        ops.run_op("api-write", {"parser_plan": "{not json", "confirmed_write": True},
                   config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)


def test_report_no_download_block_uses_stage_path(monkeypatch):
    """When no download block is present, the path-copy stage is called (not stage_bytes)."""
    def call_op(op, body, *, base_url, auth):
        return {"op": op, "result": {"summary": {}, "saved_files": {}, "rows": {}}}

    monkeypatch.setattr(ops.ns_client, "call_op", call_op)
    stage_called = []

    def my_stage(op, result):
        stage_called.append(op)
        return result

    out = ops.run_op("report", {"mode": "published", "project": "Published Data"},
                     config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
                     stage=my_stage)
    assert "report" in stage_called


def test_http_base_url_and_auth_forwarded(fake_client):
    calls, _ = fake_client

    class MyCfg:
        base_url = "http://myns:8000"
        auth = ("myuser", "mypass")

    ops.run_op("entity", {"query": "q"}, config=MyCfg(), session=None,
               write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE)
    assert calls["entity"]["base_url"] == "http://myns:8000"
    assert calls["entity"]["auth"] == ("myuser", "mypass")


# ---- FIX 3 (M-1): untested branch coverage ----------------------------------

def test_api_write_with_query_includes_query_in_body(fake_client):
    """_api_write optional-query forwarding (ops.py line ~112): truthy query is included."""
    calls, _ = fake_client
    ops.run_op(
        "api-write",
        {"parser_plan": '{"mode": "x"}', "confirmed_write": True, "query": "find sample ABC"},
        config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL, stage=ops.NO_STAGE,
    )
    assert calls["api-write"]["body"]["query"] == "find sample ABC"


def test_generate_submission_with_query_includes_query_in_body(fake_client):
    """_generate_submission optional-query forwarding (ops.py line ~139): truthy query included."""
    calls, fetched = fake_client
    ops.run_op(
        "generate-submission",
        {"type": "GEO", "uids": "UID1", "query": "find organism mouse"},
        config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
        stage=ops.NO_STAGE, stage_bytes=ops.NO_STAGE_BYTES, commit_bytes=ops.NO_COMMIT,
    )
    assert calls["generate-submission"]["body"]["query"] == "find organism mouse"


def test_generate_submission_no_download_block_uses_stage_path(monkeypatch):
    """When no download block is present for generate-submission, path-copy stage is called
    (ops.py line ~155 — mirrors test_report_no_download_block_uses_stage_path)."""
    def call_op(op, body, *, base_url, auth):
        return {"op": op, "result": {"report_writer_output": {"report_type": "GEO"}}}

    monkeypatch.setattr(ops.ns_client, "call_op", call_op)
    stage_called = []

    def my_stage(op, result):
        stage_called.append(op)
        return result

    out = ops.run_op(
        "generate-submission",
        {"type": "GEO", "uids": "UID1"},
        config=_Cfg(), session=None, write_gate=ops.ALLOW_ALL,
        stage=my_stage,
    )
    assert "generate-submission" in stage_called
