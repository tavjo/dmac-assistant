"""Tests for sidecar/app/granular_models.py (T15, A-5).

TDD step 1: failing tests written before implementation.
"""
import pytest
from pydantic import ValidationError
from sidecar.app.granular_models import (ApiWriteRequest, EntityOpRequest,
                                         ReportOpResponse, DownloadRef)


def test_api_write_confirmed_is_strict_bool():
    assert ApiWriteRequest(parser_plan="{}", confirmed_write=True).confirmed_write is True
    with pytest.raises(ValidationError):           # "true"/1 rejected at the boundary (strict bool)
        ApiWriteRequest(parser_plan="{}", confirmed_write="true")
    with pytest.raises(ValidationError):
        ApiWriteRequest(parser_plan="{}", confirmed_write=1)


def test_api_write_defaults_unconfirmed():
    assert ApiWriteRequest(parser_plan="{}").confirmed_write is False


def test_entity_request_body_field():
    assert EntityOpRequest(query="q").model_dump()["query"] == "q"


def test_report_response_download_optional():
    r = ReportOpResponse(op="report", result={"summary": {}, "saved_files": {}, "rows": {}})
    assert r.download is None
    # DownloadRef.session_id is typed UUID (models_api.py:414) — use a VALID UUID
    # literal here; a non-UUID string ("s") fails Pydantic v2 validation and would
    # keep this test permanently RED even after a correct implementation (F-T15-1).
    r2 = ReportOpResponse(op="report", result={"saved_files": {"k": "/p"}},
        download=DownloadRef(session_id="12345678-1234-4234-8234-123456789012", bundle_id=1,
                             artifacts=[{"key": "k", "url": "/nextseek_api/assistant/sessions/12345678-1234-4234-8234-123456789012/bundles/1/artifacts/k/"}]))
    assert r2.download.artifacts[0].key == "k"


def test_report_op_request_mode_validator():
    # exercises the @field_validator("mode") body so the 95% gate is achievable (F-T15-2)
    from sidecar.app.granular_models import ReportOpRequest
    assert ReportOpRequest(mode="published", project="Published Data").mode == "published"
    with pytest.raises(ValidationError):              # not in _REPORT_MODES
        ReportOpRequest(mode="bogus", project="Published Data")


def test_submission_request_type_and_uids_validators():
    # exercises the @field_validator("type") + @field_validator("uids") bodies (F-T15-2)
    from sidecar.app.granular_models import SubmissionRequest
    ok = SubmissionRequest(type="GEO", uids="UID1,UID2")
    assert ok.type == "GEO" and ok.uids == "UID1,UID2"
    with pytest.raises(ValidationError):              # type not in _SUBMISSION_TYPES
        SubmissionRequest(type="BOGUS", uids="UID1")
    with pytest.raises(ValidationError):              # empty / whitespace-only uids
        SubmissionRequest(type="GEO", uids=" , ")
