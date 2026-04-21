"""Unit tests for tests/harness/plugin_schema.py."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.harness.plugin_schema import (
    ListResponse,
    SampleSummary,
    parse_list_response,
)


# ---------- SampleSummary ----------

def test_sample_summary_minimum_viable() -> None:
    s = SampleSummary(uid="UID-1")
    assert s.uid == "UID-1"
    assert s.title is None
    assert s.sample_type is None


def test_sample_summary_full_fields() -> None:
    s = SampleSummary.model_validate({
        "uid": "UID-2",
        "title": "Tissue",
        "sample_type": "TIS",
        "project_id": "SRP",
        "extra_field_tolerated": 123,
    })
    assert s.uid == "UID-2"
    assert s.title == "Tissue"
    assert s.sample_type == "TIS"
    assert s.project_id == "SRP"


def test_sample_summary_requires_uid() -> None:
    with pytest.raises(ValidationError):
        SampleSummary.model_validate({"title": "no-uid"})


# ---------- ListResponse ----------

def test_list_response_canonical_drf_shape() -> None:
    payload = {
        "count": 3,
        "next": None,
        "results": [
            {"uid": "UID-A"},
            {"uid": "UID-B"},
            {"uid": "UID-C"},
        ],
    }
    r = ListResponse.model_validate(payload)
    assert r.count == 3
    assert len(r.records) == 3
    assert [rec.uid for rec in r.records] == ["UID-A", "UID-B", "UID-C"]


def test_list_response_records_alias_accepted() -> None:
    """Some endpoints return `records` instead of `results`."""
    payload = {"count": 1, "records": [{"uid": "UID-X"}]}
    r = ListResponse.model_validate(payload)
    assert r.count == 1
    assert r.records[0].uid == "UID-X"


def test_list_response_total_alias_accepted() -> None:
    """SKILL.md Example 3 returns `total` instead of `count` on bulk-retrieve."""
    payload = {"total": 3, "results": [{"uid": "U1"}, {"uid": "U2"}, {"uid": "U3"}]}
    r = ListResponse.model_validate(payload)
    assert (r.count or r.total) == 3
    assert len(r.records) == 3


def test_list_response_count_only_allowed() -> None:
    """Count-endpoints may omit results entirely."""
    r = ListResponse.model_validate({"count": 42})
    assert r.count == 42
    assert r.records == []


def test_list_response_total_only_allowed() -> None:
    """Bulk-retrieve may return only {total}."""
    r = ListResponse.model_validate({"total": 7})
    assert r.total == 7
    assert r.records == []


def test_list_response_results_only_allowed() -> None:
    """Some responses return results without count."""
    r = ListResponse.model_validate({"results": [{"uid": "UID-Z"}]})
    assert r.count is None
    assert len(r.records) == 1


def test_list_response_has_any_record_semantics() -> None:
    assert ListResponse(count=42).has_any_record() is True
    assert ListResponse(total=3).has_any_record() is True
    assert ListResponse(records=[SampleSummary(uid="x")]).has_any_record() is True
    assert ListResponse(count=0).has_any_record() is False
    assert ListResponse(total=0).has_any_record() is False
    assert ListResponse().has_any_record() is False


def test_list_response_rejects_non_dict() -> None:
    with pytest.raises(ValidationError):
        ListResponse.model_validate("not a dict")


def test_list_response_records_and_results_both_present_records_wins() -> None:
    """When both keys are present, `records` is the explicit-wins value."""
    payload = {
        "count": 1,
        "records": [{"uid": "RECORDS-WIN"}],
        "results": [{"uid": "RESULTS-DROPPED"}],
    }
    r = ListResponse.model_validate(payload)
    assert [rec.uid for rec in r.records] == ["RECORDS-WIN"]


def test_list_response_count_and_total_both_present_preserved() -> None:
    """Both fields preserved verbatim when both are supplied."""
    payload = {"count": 7, "total": 9, "results": [{"uid": "U"}]}
    r = ListResponse.model_validate(payload)
    assert r.count == 7
    assert r.total == 9


def test_list_response_rows_alias_accepted() -> None:
    """Live NExtSEEK list endpoints return ``rows`` (not ``results``/``records``)."""
    payload = {
        "total": 30,
        "rows": [
            {"uid": "<a href='x'>U-A</a>"},
            {"uid": "<a href='x'>U-B</a>"},
        ],
        "footer": [],
        "msg": "okay",
    }
    r = ListResponse.model_validate(payload)
    assert r.total == 30
    assert len(r.records) == 2
    assert r.records[0].uid.endswith("U-A</a>")


def test_list_response_records_overrides_rows() -> None:
    """Explicit ``records`` wins over both ``results`` and ``rows``."""
    payload = {
        "records": [{"uid": "EXPLICIT"}],
        "results": [{"uid": "DROPPED-1"}],
        "rows": [{"uid": "DROPPED-2"}],
    }
    r = ListResponse.model_validate(payload)
    assert [rec.uid for rec in r.records] == ["EXPLICIT"]


def test_list_response_results_overrides_rows() -> None:
    """``results`` wins over ``rows`` when ``records`` absent."""
    payload = {
        "results": [{"uid": "RESULTS-WIN"}],
        "rows": [{"uid": "DROPPED"}],
    }
    r = ListResponse.model_validate(payload)
    assert [rec.uid for rec in r.records] == ["RESULTS-WIN"]


def test_list_response_total_samples_alias_accepted() -> None:
    """Live NExtSEEK summary endpoints return ``total_samples``."""
    payload = {"total_samples": 4, "total_sample_types": 2, "data": []}
    r = ListResponse.model_validate(payload)
    assert r.count == 4
    assert r.total == 4
    assert r.has_any_record() is True


def test_has_any_record_fallback_jsonapi_data_array() -> None:
    """JSON:API endpoints return ``data: [{id, type, attributes, links}, ...]``
    with no canonical count — the extras-walking fallback must accept it."""
    payload = {
        "data": [
            {"id": "1", "type": "sample_types", "attributes": {"title": "TIS"}},
            {"id": "2", "type": "sample_types", "attributes": {"title": "DNA"}},
        ],
        "jsonapi": {"version": "1.0"},
    }
    r = ListResponse.model_validate(payload)
    # Items live in extras (not coalesced into `records`); identifier-walking
    # has_any_record sees them.
    assert r.records == []
    assert r.count is None
    assert r.has_any_record() is True


def test_has_any_record_fallback_rejects_list_of_strings() -> None:
    payload = {"colors": ["red", "green"]}
    r = ListResponse.model_validate(payload)
    assert r.has_any_record() is False


def test_has_any_record_fallback_rejects_dicts_without_identifiers() -> None:
    payload = {"data": [{"foo": "bar"}, {"baz": 1}]}
    r = ListResponse.model_validate(payload)
    assert r.has_any_record() is False


def test_has_any_record_fallback_empty_list() -> None:
    payload = {"data": []}
    r = ListResponse.model_validate(payload)
    assert r.has_any_record() is False


def test_list_response_rejects_malformed_results() -> None:
    with pytest.raises(ValidationError):
        ListResponse.model_validate({"results": [{"not_uid": "x"}]})


# ---------- parse_list_response ----------

def test_parse_list_response_from_json_string() -> None:
    payload = json.dumps({"count": 1, "results": [{"uid": "UID-1"}]})
    r = parse_list_response(payload)
    assert r.has_any_record()


def test_parse_list_response_from_dict() -> None:
    r = parse_list_response({"count": 5})
    assert r.count == 5


def test_parse_list_response_raises_on_invalid_json() -> None:
    with pytest.raises(ValueError):
        parse_list_response("not json")


def test_parse_list_response_raises_on_null() -> None:
    with pytest.raises(ValueError):
        parse_list_response("null")


def test_parse_list_response_raises_on_json_array() -> None:
    """JSON list parses to a Python list — must reject as non-object."""
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_list_response("[1, 2, 3]")


@pytest.mark.parametrize(
    "payload",
    [
        {"count": 1, "results": [{"uid": "U"}]},
        {"count": 1, "records": [{"uid": "U"}]},
        {"results": [{"uid": "U"}]},
        {"total": 1, "results": [{"uid": "U"}]},
        {"total": 3},
    ],
)
def test_parse_list_response_parametric_happy(payload: dict) -> None:
    r = parse_list_response(payload)
    assert r.has_any_record()
