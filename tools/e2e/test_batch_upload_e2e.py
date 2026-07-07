from __future__ import annotations

import inspect

import orjson

from tools.e2e import run_batch_upload_e2e as harness
from tools.e2e.ledger import SpendLedger


def test_c8_regression_refuses_empty_local(tmp_path):
    result = harness.run_c8_regression(tmp_path)
    assert result.rc != 0
    assert result.marker == {"gate": "non_empty"}
    assert result.artifact is None
    assert result.validate_posts == []

    create = harness.run_create_positive_control(tmp_path / "create")
    assert create.rc == 0
    assert create.artifact is not None
    row = harness.workbook_rows(create.artifact)[0]
    assert orjson.loads(row["json_metadata"]) == {
        "Name": "sample",
        "Scientist": "Curator",
        "Parent": "P1",
    }

    update = harness.run_update_positive_control(tmp_path / "update")
    assert update.rc == 0
    assert update.artifact is not None
    assert update.validate_posts
    assert "multipart/form-data" in update.validate_posts[0]["content_type"]
    assert 'name="checks"' in update.validate_posts[0]["body"]
    assert "structure,name_check,dag" in update.validate_posts[0]["body"]
    update_row = harness.workbook_rows(update.artifact)[0]
    assert orjson.loads(update_row["json_metadata"]) == {
        "UID": "D.IMG-230913ENG-1757-PUB",
        "Treatment": "drug",
    }
    assert {306, 351} <= set(orjson.loads(update_row["assay_ids"]))


def test_bedrock_cost_exact():
    ledger = SpendLedger()
    frame = {
        "result": {
            "model": "claude-opus-4-8 (Bedrock, via proxy)",
            "usage": {"input_tokens": 1234, "output_tokens": 56},
            "total_cost_usd": 0.123456,
        }
    }
    captured = harness.record_bedrock_result(frame, ledger)
    assert captured == frame["result"] | {"usage": frame["result"]["usage"]}
    assert ledger.running_usd == 0.123456


def test_gemini_cost_distinct_source():
    cc_frame = {
        "result": {
            "usage": {"input_tokens": 777, "output_tokens": 88},
            "total_cost_usd": 9.99,
        }
    }
    gemini = harness.record_gemini_cost(
        {
            "model": "gemini-3.1-pro-preview (GCPReasoner)",
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "total_cost_usd": 0.0042,
        },
        cc_frame,
    )
    assert gemini["total_cost_usd"] == 0.0042
    assert gemini["total_cost_usd"] != cc_frame["result"]["total_cost_usd"]
    assert harness.record_gemini_cost(None, cc_frame) == {"gemini_cost": "unavailable"}


def test_hb_delivery_summary():
    summary = harness.delivery_summary(
        [
            {"UID": "", "attributes": {"Name": "new"}},
            {"UID": "D.IMG-230913ENG-1757-PUB", "attributes": {"Treatment": "drug"}},
        ]
    )
    assert summary["update_rows"] == 1
    assert summary["create_rows"] == 1
    assert summary["mixed_create_update"] is True
    assert "update_existing=true" in summary["update_existing_note"]


def test_ast_cost_guard_rejects_literal():
    source = inspect.getsource(harness.record_bedrock_result)
    assert harness.cost_guard_violations(source) == []
    bad = """
def record_bedrock_result(frame, ledger):
    est = 1500
    ledger.record("bedrock", model="m", in_tokens=est, out_tokens=0, actual_usd=1.0)
"""
    direct = """
def record_bedrock_result(frame, ledger):
    ledger.record("bedrock", model="m", in_tokens=1500, out_tokens=0, actual_usd=1.0)
"""
    assert harness.cost_guard_violations(bad)
    assert harness.cost_guard_violations(direct)
