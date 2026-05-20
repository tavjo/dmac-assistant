"""R3 — tests for run_router_batch.assemble_manifest().

Companion to plan llm-router-headless-batch-2026-05-18.md (TDD step R3).

Asserts that the manifest dict assembled by run_router_batch.py contains:
  - Every top-level key render_report.py reads (queries_total,
    queries_answered, queries_errored, queries_timed_out, answer_rate,
    total_cost_usd, avg_cost_usd, total_latency_seconds,
    avg_latency_seconds, started_at, completed_at, corpus, image, run_id,
    timeout_seconds, summaries).
  - The seven router additions per record (route, model_class, model_id,
    router_decision_latency_ms, router_reasoning_len, router_fallback) and
    null-on-NS distinction for cost_usd/num_turns/stop_reason.
  - A `router_summary` block aggregating route counts, model-class counts,
    fallback count, and avg decision latency.
"""
from __future__ import annotations

import json

import pytest

from tools.e2e import run_router_batch  # noqa: E402  (module created in G3)


# Keys render_report.py reads at top-level (introspected from
# tools/e2e/render_report.py 2026-05-19).
_RENDER_REPORT_TOPLEVEL_KEYS = {
    "summaries",
    "queries_total", "queries_answered", "queries_errored",
    "queries_timed_out",
    "answer_rate",
    "total_cost_usd", "avg_cost_usd",
    "total_latency_seconds", "avg_latency_seconds",
    "started_at", "completed_at",
    "corpus", "image", "run_id",
    "timeout_seconds",
}

# Keys render_report.py reads from each summary[].
_RENDER_REPORT_SUMMARY_KEYS = {
    "query_id", "query_text", "latency_seconds", "cost_usd", "is_error",
    "tool_use_summary",
}

# Router-batch additions per record.
_ROUTER_RECORD_KEYS = {
    "route", "model_class", "model_id",
    "router_decision_latency_ms", "router_reasoning_len",
    "router_fallback",
}


def _fake_records() -> list[dict]:
    return [
        {
            # CC route, sonnet — with promoted artifacts
            "query_id": "Q1",
            "query_text": "find me mice",
            "latency_seconds": 12.3,
            "cost_usd": 0.07,
            "is_error": False,
            "tool_use_summary": [{"tool": "Bash", "count": 2}],
            "num_turns": 4,
            "stop_reason": "end_turn",
            "timed_out": False,
            "artifacts": [
                "/path/to/session/artifacts/Q1/report.xlsx",
                "/path/to/session/artifacts/Q1/summary.pdf",
            ],
            "route": "container_cc",
            "model_class": "sonnet",
            "model_id":
                "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "router_decision_latency_ms": 1240.0,
            "router_reasoning_len": 130,
            "router_fallback": False,
        },
        {
            # NS route — CC-only metrics MUST be null
            "query_id": "Q2",
            "query_text": "how many samples in proj-X?",
            "latency_seconds": 4.1,
            "cost_usd": None,
            "is_error": False,
            "tool_use_summary": [],
            "num_turns": None,
            "stop_reason": None,
            "timed_out": False,
            "route": "nextseek_query",
            "model_class": None,
            "model_id": None,
            "router_decision_latency_ms": 980.0,
            "router_reasoning_len": 88,
            "router_fallback": False,
        },
        {
            # CC route, fallback (BAML failed)
            "query_id": "Q3",
            "query_text": "do a thing",
            "latency_seconds": 22.0,
            "cost_usd": 0.10,
            "is_error": True,
            "tool_use_summary": [],
            "num_turns": 2,
            "stop_reason": "error",
            "timed_out": False,
            "route": "container_cc",
            "model_class": "sonnet",
            "model_id":
                "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "router_decision_latency_ms": 50.0,
            "router_reasoning_len": 0,
            "router_fallback": True,
        },
    ]


def _build():
    return run_router_batch.assemble_manifest(
        run_id="20260519T000000Z",
        started_at="2026-05-19T00:00:00+00:00",
        completed_at="2026-05-19T00:00:20+00:00",
        image="dmac-assistant:poc",
        corpus="evidence/full-corpus-2026-05-07/corpus.json",
        corpus_key=None,
        timeout_seconds=180,
        max_budget_usd=0.50,
        records=_fake_records(),
    )


def test_manifest_has_all_render_report_toplevel_keys():
    m = _build()
    missing = _RENDER_REPORT_TOPLEVEL_KEYS - set(m.keys())
    assert not missing, (
        f"manifest missing keys render_report.py reads: {sorted(missing)}"
    )


def test_manifest_summaries_have_all_render_report_keys():
    m = _build()
    for i, s in enumerate(m["summaries"]):
        missing = _RENDER_REPORT_SUMMARY_KEYS - set(s.keys())
        assert not missing, (
            f"summary[{i}] (qid={s.get('query_id')}) missing render_report.py "
            f"keys: {sorted(missing)}"
        )


def test_manifest_summaries_have_all_router_record_keys():
    m = _build()
    for i, s in enumerate(m["summaries"]):
        missing = _ROUTER_RECORD_KEYS - set(s.keys())
        assert not missing, (
            f"summary[{i}] (qid={s.get('query_id')}) missing router keys: "
            f"{sorted(missing)}"
        )


def test_manifest_ns_route_cc_only_fields_are_null():
    m = _build()
    ns = next(s for s in m["summaries"] if s["route"] == "nextseek_query")
    assert ns["cost_usd"] is None
    assert ns["num_turns"] is None
    assert ns["stop_reason"] is None
    assert ns["model_id"] is None
    assert ns["model_class"] is None


def test_manifest_has_router_summary_block():
    m = _build()
    rs = m.get("router_summary")
    assert isinstance(rs, dict), "router_summary block must be a dict"
    expected = {
        "queries_routed_cc",
        "queries_routed_ns",
        "queries_routed_fallback",
        "by_model_class",
        "avg_router_decision_latency_ms",
    }
    missing = expected - set(rs.keys())
    assert not missing, f"router_summary missing keys: {sorted(missing)}"


def test_router_summary_counts_correct():
    m = _build()
    rs = m["router_summary"]
    assert rs["queries_routed_cc"] == 2
    assert rs["queries_routed_ns"] == 1
    assert rs["queries_routed_fallback"] == 1


def test_router_summary_by_model_class_correct():
    m = _build()
    by = m["router_summary"]["by_model_class"]
    # null bucket holds NS-route rows (model_class=None)
    assert by.get("sonnet", 0) == 2
    assert by.get("null", 0) == 1 or by.get(None, 0) == 1


def test_aggregate_counts_match_records():
    m = _build()
    assert m["queries_total"] == 3
    # CC-routed Q1 + NS Q2 succeed; Q3 errored.
    assert m["queries_answered"] + m["queries_errored"] \
        + m["queries_timed_out"] == m["queries_total"]
    assert m["queries_errored"] >= 1


def test_aggregate_cost_excludes_nulls():
    m = _build()
    # 0.07 + 0.10, NS row's None excluded.
    assert m["total_cost_usd"] == pytest.approx(0.17, rel=1e-6)


def test_avg_router_decision_latency_ms_computed():
    m = _build()
    rs = m["router_summary"]
    avg = rs["avg_router_decision_latency_ms"]
    assert avg == pytest.approx((1240.0 + 980.0 + 50.0) / 3, rel=1e-6)


def test_manifest_summaries_carry_artifacts_field():
    """Each summary must have an `artifacts` list (matches run_batch.py).
    Q1 in the fixture has two artifacts; Q2 and Q3 have none."""
    m = _build()
    by_id = {s["query_id"]: s for s in m["summaries"]}
    assert by_id["Q1"]["artifacts"] == [
        "/path/to/session/artifacts/Q1/report.xlsx",
        "/path/to/session/artifacts/Q1/summary.pdf",
    ]
    assert by_id["Q2"]["artifacts"] == []
    assert by_id["Q3"]["artifacts"] == []


# ----------------------- pure-helper coverage (corpus + scratch resolution)


def _write_corpus(tmp_path, payload):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(payload))
    return p


def test_resolve_query_list_flat_queries_key(tmp_path):
    """Mirrors evidence/full-corpus-2026-05-07/corpus.json shape."""
    p = _write_corpus(tmp_path, {
        "queries": [
            {"id": "Q1", "query": "hello"},
            {"id": "Q2", "query": "world"},
        ],
        "_meta": {"source": "x"},
    })
    pairs = run_router_batch._resolve_query_list(p, None, None, None)
    assert pairs == [("Q1", "hello"), ("Q2", "world")]


def test_resolve_query_list_nested_full_test_tests(tmp_path):
    """testing.json shape: {full_test: {description, tests: [...]}}."""
    p = _write_corpus(tmp_path, {
        "full_test": {
            "description": "x",
            "tests": [
                {"id": "Search-Basic-1", "query": "find mice"},
            ],
        },
    })
    pairs = run_router_batch._resolve_query_list(p, "full_test", None, None)
    assert pairs == [("Search-Basic-1", "find mice")]


def test_resolve_query_list_limit(tmp_path):
    p = _write_corpus(tmp_path, {
        "queries": [{"id": f"Q{i}", "query": f"q{i}"} for i in range(5)],
    })
    pairs = run_router_batch._resolve_query_list(p, None, 2, None)
    assert len(pairs) == 2
    assert pairs[0] == ("Q0", "q0")


def test_resolve_query_list_ids_filter(tmp_path):
    p = _write_corpus(tmp_path, {
        "queries": [{"id": f"Q{i}", "query": f"q{i}"} for i in range(5)],
    })
    pairs = run_router_batch._resolve_query_list(p, None, None, ["Q3", "Q1"])
    # ordering preserved per corpus order
    assert [pid for pid, _ in pairs] == ["Q1", "Q3"]


def test_resolve_query_list_missing_ids_raises(tmp_path):
    p = _write_corpus(tmp_path, {"queries": [{"id": "Q1", "query": "x"}]})
    with pytest.raises(SystemExit, match="not found"):
        run_router_batch._resolve_query_list(p, None, None, ["Q9"])


def test_resolve_query_list_missing_corpus_key_raises(tmp_path):
    p = _write_corpus(tmp_path, {"smart_test": {"tests": []}})
    with pytest.raises(SystemExit, match="not found"):
        run_router_batch._resolve_query_list(p, "full_test", None, None)


def test_resolve_query_list_unsupported_shape_raises(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(42))  # neither list nor dict
    with pytest.raises(SystemExit, match="Unsupported corpus shape"):
        run_router_batch._resolve_query_list(p, None, None, None)


def test_resolve_query_list_cannot_locate_list_raises(tmp_path):
    p = _write_corpus(tmp_path, {"unknown_key": []})
    with pytest.raises(SystemExit, match="Could not locate query list"):
        run_router_batch._resolve_query_list(p, None, None, None)


def test_resolve_query_list_bare_list_supported(tmp_path):
    p = _write_corpus(tmp_path, [
        {"id": "Q1", "query": "hello"},
    ])
    pairs = run_router_batch._resolve_query_list(p, None, None, None)
    assert pairs == [("Q1", "hello")]


def test_resolve_query_list_skips_non_dict_entries(tmp_path):
    """Defensive: malformed list items (strings, None) must not crash."""
    p = _write_corpus(tmp_path, {
        "queries": [
            "garbage",
            None,
            {"id": "Q1", "query": "good"},
            {"id": "Q2"},  # missing query text — skipped
            {"query": "no id"},  # missing id — skipped
        ],
    })
    pairs = run_router_batch._resolve_query_list(p, None, None, None)
    assert pairs == [("Q1", "good")]


def test_resolve_scratch_from_env_happy_path():
    env = {
        "DMAC_DROPBOX_ROOT": "/tmp/dropbox-root",
        "DMAC_USERS": json.dumps({
            "demo": {"projects": ["example-project"]},
        }),
    }
    path = run_router_batch._resolve_scratch_from_env(env)
    assert str(path).endswith("dropbox-root/example-project")


def test_resolve_scratch_from_env_missing_dropbox_root():
    with pytest.raises(SystemExit, match="DMAC_DROPBOX_ROOT"):
        run_router_batch._resolve_scratch_from_env({})


def test_resolve_scratch_from_env_missing_users():
    with pytest.raises(SystemExit, match="DMAC_USERS"):
        run_router_batch._resolve_scratch_from_env(
            {"DMAC_DROPBOX_ROOT": "/tmp/x"},
        )


def test_resolve_scratch_from_env_empty_projects():
    env = {
        "DMAC_DROPBOX_ROOT": "/tmp/x",
        "DMAC_USERS": json.dumps({"demo": {"projects": []}}),
    }
    with pytest.raises(SystemExit, match="no projects"):
        run_router_batch._resolve_scratch_from_env(env)
