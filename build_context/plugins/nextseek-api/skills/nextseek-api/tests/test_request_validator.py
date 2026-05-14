"""Tests for request_validator: static pre-flight request validation.

These tests are the authoritative contract for task-06. The implementation
in scripts/lib/request_validator.py must satisfy every assertion without
modification.
"""

from __future__ import annotations

from typing import Any

from lib.models import FullEndpoint, RequestSpec
from lib.request_validator import (
    FieldError,
    ValidationResult,
    humanize_validation_error,
    validate_request,
)
from pydantic import ValidationError as PydanticValidationError


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def make_endpoint(
    *,
    operation_id: str = "samples_retrieve",
    path: str = "/nextseek_api/samples/{uid}/",
    method: str = "GET",
    parameters: dict[str, Any] | None = None,
    request_schema: dict[str, Any] | None = None,
) -> FullEndpoint:
    return FullEndpoint(
        operationId=operation_id,
        path=path,
        method=method,
        description="Test endpoint",
        tags=["test"],
        parameters=parameters or {},
        request_schema=request_schema or {},
        response_schema=None,
        examples=[],
        relevance_score=0.8,
    )


def make_spec(
    *,
    operation_id: str = "samples_retrieve",
    method: str = "GET",
    endpoint: str = "/nextseek_api/samples/{uid}/",
    path_params: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    request_body: dict[str, Any] | None = None,
) -> RequestSpec:
    return RequestSpec(
        operation_id=operation_id,
        method=method,
        endpoint=endpoint,
        path_params=path_params or {},
        query_params=query_params or {},
        headers=headers or {},
        request_body=request_body,
    )


# ---------------------------------------------------------------------------
# Test 1: valid GET request passes
# ---------------------------------------------------------------------------


def test_valid_get_request_passes() -> None:
    endpoint = make_endpoint(
        operation_id="samples_retrieve",
        path="/nextseek_api/samples/{uid}/",
        method="GET",
        parameters={"uid": {"in": "path", "required": True, "type": "string"}},
    )
    spec = make_spec(
        operation_id="samples_retrieve",
        method="GET",
        endpoint="/nextseek_api/samples/{uid}/",
        path_params={"uid": "SMP-1"},
    )

    result = validate_request(spec, endpoint)

    assert isinstance(result, ValidationResult)
    assert result.passed is True, f"expected pass, got errors: {result.errors}"
    assert result.errors == []
    assert result.rendered_path == "/nextseek_api/samples/SMP-1/"


# ---------------------------------------------------------------------------
# Test 2: missing path param fails
# ---------------------------------------------------------------------------


def test_missing_path_param_fails() -> None:
    endpoint = make_endpoint(path="/nextseek_api/samples/{uid}/", method="GET")
    spec = make_spec(
        method="GET",
        endpoint="/nextseek_api/samples/{uid}/",
        path_params={},  # missing uid
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "MISSING_PATH_PARAM" in codes
    missing = next(e for e in result.errors if e.code == "MISSING_PATH_PARAM")
    assert "uid" in missing.message


# ---------------------------------------------------------------------------
# Test 3: path param interpolation (nested-brace-safe)
# ---------------------------------------------------------------------------


def test_path_param_interpolation() -> None:
    """Template /samples/{uid}/ + path_params {uid: "A1"} -> /samples/A1/."""
    endpoint = make_endpoint(path="/samples/{uid}/", method="GET")
    spec = make_spec(
        endpoint="/samples/{uid}/",
        method="GET",
        path_params={"uid": "A1"},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is True
    assert result.rendered_path == "/samples/A1/"


# ---------------------------------------------------------------------------
# Test 4: method mismatch fails
# ---------------------------------------------------------------------------


def test_method_mismatch_fails() -> None:
    endpoint = make_endpoint(
        operation_id="samples_list",
        path="/nextseek_api/samples/",
        method="POST",
    )
    spec = make_spec(
        operation_id="samples_list",
        method="GET",
        endpoint="/nextseek_api/samples/",
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "METHOD_MISMATCH" in codes
    msg = next(e.message for e in result.errors if e.code == "METHOD_MISMATCH")
    assert "GET" in msg
    assert "POST" in msg


# ---------------------------------------------------------------------------
# Test 5: endpoint path mismatch fails
# ---------------------------------------------------------------------------


def test_endpoint_path_mismatch_fails() -> None:
    endpoint = make_endpoint(
        operation_id="samples_retrieve",
        path="/nextseek_api/samples/{uid}/",
        method="GET",
    )
    spec = make_spec(
        operation_id="samples_retrieve",
        method="GET",
        endpoint="/nextseek_api/studies/{uid}/",  # WRONG path
        path_params={"uid": "X1"},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "ENDPOINT_PATH_MISMATCH" in codes


# ---------------------------------------------------------------------------
# Test 6: missing required query param fails
# ---------------------------------------------------------------------------


def test_missing_required_query_param_fails() -> None:
    endpoint = make_endpoint(
        operation_id="samples_list",
        path="/nextseek_api/samples/",
        method="GET",
        parameters={
            "project_id": {"in": "query", "required": True, "type": "string"},
            "limit": {"in": "query", "required": False, "type": "integer"},
        },
    )
    spec = make_spec(
        operation_id="samples_list",
        method="GET",
        endpoint="/nextseek_api/samples/",
        query_params={"limit": 20},  # project_id missing
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "MISSING_REQUIRED_PARAM" in codes
    msg = next(e.message for e in result.errors if e.code == "MISSING_REQUIRED_PARAM")
    assert "project_id" in msg


# ---------------------------------------------------------------------------
# Test 7: missing required body field fails
# ---------------------------------------------------------------------------


def test_missing_required_body_field_fails() -> None:
    endpoint = make_endpoint(
        operation_id="schema_rag_retrieve",
        path="schema_rag/retrieve/",
        method="POST",
        request_schema={
            "type": "object",
            "required": ["query", "session_id"],
            "properties": {
                "query": {"type": "string"},
                "session_id": {"type": "string"},
                "mode": {"type": "string"},
            },
        },
    )
    spec = make_spec(
        operation_id="schema_rag_retrieve",
        method="POST",
        endpoint="schema_rag/retrieve/",
        request_body={"query": "find samples"},  # missing session_id
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "MISSING_REQUIRED_BODY_FIELD" in codes
    msg = next(e.message for e in result.errors if e.code == "MISSING_REQUIRED_BODY_FIELD")
    assert "session_id" in msg


# ---------------------------------------------------------------------------
# Test 8: denylist blocks non-GET containing "upload"
# ---------------------------------------------------------------------------


def test_denylist_blocks_non_get_with_upload() -> None:
    """POST with operation_id containing 'upload' must fail denylist check."""
    endpoint = make_endpoint(
        operation_id="samples_upload_bulk",
        path="/nextseek_api/samples/upload/",
        method="POST",
        request_schema={"type": "object"},
    )
    spec = make_spec(
        operation_id="samples_upload_bulk",
        method="POST",
        endpoint="/nextseek_api/samples/upload/",
        request_body={"file": "abc"},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "DENYLIST_BLOCK" in codes


# ---------------------------------------------------------------------------
# Test 9: schema_rag POST bypasses denylist
# ---------------------------------------------------------------------------


def test_schema_rag_post_bypasses_denylist() -> None:
    """POST to schema_rag/retrieve/ must pass — schema_rag is whitelisted."""
    endpoint = make_endpoint(
        operation_id="schema_rag_retrieve",
        path="schema_rag/retrieve/",
        method="POST",
        request_schema={"type": "object", "required": ["query"]},
    )
    spec = make_spec(
        operation_id="schema_rag_retrieve",
        method="POST",
        endpoint="schema_rag/retrieve/",
        request_body={"query": "find samples"},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is True, f"expected schema_rag POST to pass, got {result.errors}"
    assert all(e.code != "DENYLIST_BLOCK" for e in result.errors)


# ---------------------------------------------------------------------------
# Test 10: unsupported method (DELETE) fails
# ---------------------------------------------------------------------------


def test_unsupported_method_fails() -> None:
    endpoint = make_endpoint(
        operation_id="samples_destroy",
        path="/nextseek_api/samples/{uid}/",
        method="DELETE",
    )
    spec = make_spec(
        operation_id="samples_destroy",
        method="DELETE",
        endpoint="/nextseek_api/samples/{uid}/",
        path_params={"uid": "SMP-9"},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "UNSUPPORTED_METHOD" in codes
    msg = next(e.message for e in result.errors if e.code == "UNSUPPORTED_METHOD")
    assert "DELETE" in msg


# ---------------------------------------------------------------------------
# Test 11: parameters accepts OpenAPI-native list form (CL-6)
# ---------------------------------------------------------------------------


def test_parameters_accepts_list_form() -> None:
    """FullEndpoint.parameters given as a list of dicts (OpenAPI-native shape)
    must be normalized and validated correctly. CL-6 invariant."""
    endpoint = make_endpoint(
        operation_id="samples_list",
        path="/nextseek_api/samples/",
        method="GET",
        parameters=[
            {"name": "project_id", "in": "query", "required": True, "type": "string"},
            {"name": "limit", "in": "query", "required": False, "type": "integer"},
        ],
    )
    # Spec missing project_id — validator must still flag it when
    # parameters came in as a list.
    spec = make_spec(
        operation_id="samples_list",
        method="GET",
        endpoint="/nextseek_api/samples/",
        query_params={"limit": 20},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "MISSING_REQUIRED_PARAM" in codes, (
        "list-form parameters must be normalized before iteration"
    )
    msg = next(e.message for e in result.errors if e.code == "MISSING_REQUIRED_PARAM")
    assert "project_id" in msg


# ---------------------------------------------------------------------------
# Test 12: parameters accepts dict-keyed form (backward compat, CL-6)
# ---------------------------------------------------------------------------


def test_parameters_accepts_dict_form() -> None:
    """FullEndpoint.parameters given as a dict-keyed-by-name (the older shape
    used in task-05 test fixtures) must continue to work. CL-6 invariant."""
    endpoint = make_endpoint(
        operation_id="samples_list",
        path="/nextseek_api/samples/",
        method="GET",
        parameters={
            "project_id": {"in": "query", "required": True, "type": "string"},
            "limit": {"in": "query", "required": False, "type": "integer"},
        },
    )
    spec = make_spec(
        operation_id="samples_list",
        method="GET",
        endpoint="/nextseek_api/samples/",
        query_params={"project_id": "P-1", "limit": 20},
    )

    result = validate_request(spec, endpoint)

    assert result.passed is True, (
        f"dict-form parameters must still pass required-field check, got: {result.errors}"
    )


# ---------------------------------------------------------------------------
# Test 13: missing required header fails with MISSING_HEADER (CL-5)
# ---------------------------------------------------------------------------


def test_missing_required_header_fails() -> None:
    """A required header parameter (in='header') not present in spec.headers
    must fail with code MISSING_HEADER. CL-5 puts `headers` on RequestSpec;
    CL-6 normalization feeds the validator the list-form entry."""
    endpoint = make_endpoint(
        operation_id="samples_list",
        path="/nextseek_api/samples/",
        method="GET",
        parameters=[
            {
                "name": "X-Request-Id",
                "in": "header",
                "required": True,
                "type": "string",
            },
        ],
    )
    spec = make_spec(
        operation_id="samples_list",
        method="GET",
        endpoint="/nextseek_api/samples/",
        headers={},  # missing X-Request-Id
    )

    result = validate_request(spec, endpoint)

    assert result.passed is False
    codes = [e.code for e in result.errors]
    assert "MISSING_HEADER" in codes, (
        f"required-header branch must fire with MISSING_HEADER, got codes: {codes}"
    )
    msg = next(e.message for e in result.errors if e.code == "MISSING_HEADER")
    assert "X-Request-Id" in msg


# ---------------------------------------------------------------------------
# task-03: humanize_validation_error — camelCase → snake_case hints (#15)
# ---------------------------------------------------------------------------


class TestValidatorHints:
    """humanize_validation_error wraps pydantic errors with actionable hints."""

    def test_camelcase_operationid(self) -> None:
        errors: list[FieldError] = []
        try:
            RequestSpec.model_validate(
                {"operationId": "ListAssays", "method": "GET", "endpoint": "assays/"}
            )
        except PydanticValidationError as exc:
            errors = humanize_validation_error(exc)
        locations = [e.location for e in errors]
        hints = [e.hint for e in errors if e.hint]
        assert any("operationId" in loc for loc in locations)
        assert any(
            "operation_id" in h and "snake_case" in h.lower() for h in hints
        )

    def test_path_to_endpoint_hint(self) -> None:
        errors: list[FieldError] = []
        try:
            RequestSpec.model_validate(
                {"operation_id": "X", "method": "GET", "path": "assays/"}
            )
        except PydanticValidationError as exc:
            errors = humanize_validation_error(exc)
        assert any(e.hint and "endpoint" in e.hint for e in errors)

    def test_body_to_request_body_hint(self) -> None:
        errors: list[FieldError] = []
        try:
            RequestSpec.model_validate(
                {
                    "operation_id": "X",
                    "method": "POST",
                    "endpoint": "x/",
                    "body": {"a": 1},
                }
            )
        except PydanticValidationError as exc:
            errors = humanize_validation_error(exc)
        assert any(e.hint and "request_body" in e.hint for e in errors)

    def test_unknown_field_no_hint(self) -> None:
        """Fields not in the snake-case map yield a FieldError with hint=None."""
        errors: list[FieldError] = []
        try:
            RequestSpec.model_validate(
                {
                    "operation_id": "X",
                    "method": "GET",
                    "endpoint": "x/",
                    "totallyRandomKey": 1,
                }
            )
        except PydanticValidationError as exc:
            errors = humanize_validation_error(exc)
        # at least one FieldError with location pointing at totallyRandomKey
        assert any("totallyRandomKey" in e.location for e in errors)
        # that error should have no hint (unknown field isn't in the map)
        for e in errors:
            if "totallyRandomKey" in e.location:
                assert e.hint is None

    def test_fielderror_fields(self) -> None:
        """FieldError has location, code, message, optional hint."""
        fe = FieldError(location="$.x", code="extra_forbidden", message="no", hint="hi")
        assert fe.location == "$.x"
        assert fe.code == "extra_forbidden"
        assert fe.message == "no"
        assert fe.hint == "hi"
        fe2 = FieldError(location="$.y", code="missing", message="m")
        assert fe2.hint is None
