"""Tests for lib.models — Pydantic v2 models for the nextseek-api plugin.

Covers:
- MinimalEndpoint alias parsing (operationId <-> operation_id)
- FullEndpoint inheritance of MinimalEndpoint fields + extension with params
- SessionState JSON round-trip (save/load preserves fields)
- SessionState.is_expired() helper on past and future timestamps
- RequestSpec validation (valid + missing fields)
- RequestSpec.method enum constraint (rejects PATCH/PUT/DELETE)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from lib.models import (
    FullEndpoint,
    IngestResponse,
    MinimalEndpoint,
    RequestSpec,
    SchemaRAGResponse,
    SessionState,
)


# ─── MinimalEndpoint ──────────────────────────────────────────────


def test_minimal_endpoint_parses_alias_operationId():
    """MinimalEndpoint accepts camelCase `operationId`/`path` via alias, snake_case via populate_by_name."""
    # Via alias
    ep_alias = MinimalEndpoint.model_validate({
        "operationId": "getSamples",
        "path": "/nextseek_api/samples/",
        "method": "GET",
        "description": "List samples",
        "tags": ["samples", "core"],
    })
    assert ep_alias.operation_id == "getSamples"
    assert ep_alias.endpoint == "/nextseek_api/samples/"
    assert ep_alias.method == "GET"
    assert ep_alias.tags == ["samples", "core"]

    # Via python name
    ep_py = MinimalEndpoint.model_validate({
        "operation_id": "getSamples",
        "endpoint": "/nextseek_api/samples/",
    })
    assert ep_py.operation_id == "getSamples"
    assert ep_py.endpoint == "/nextseek_api/samples/"

    # by_alias=True still emits the OpenAPI wire shape (interop only;
    # nothing in the plugin uses this path — see DD-5).
    dumped_alias = ep_alias.model_dump(by_alias=True)
    assert dumped_alias["operationId"] == "getSamples"
    assert dumped_alias["path"] == "/nextseek_api/samples/"
    assert "operation_id" not in dumped_alias
    assert "endpoint" not in dumped_alias

    # DD-5: canonical snake_case dump is the agent-visible surface.
    dumped = ep_alias.model_dump()
    assert dumped["operation_id"] == "getSamples"
    assert dumped["endpoint"] == "/nextseek_api/samples/"
    assert "operationId" not in dumped
    assert "path" not in dumped


def test_minimal_endpoint_defaults():
    """Unset optional fields default to empty strings / lists / 'GET'."""
    ep = MinimalEndpoint.model_validate({"operationId": "ping"})
    assert ep.operation_id == "ping"
    assert ep.endpoint == ""
    assert ep.method == "GET"
    assert ep.description == ""
    assert ep.tags == []


def test_minimal_endpoint_ignores_extra_fields():
    """Extra fields on the wire are silently dropped (extra='ignore')."""
    ep = MinimalEndpoint.model_validate({
        "operationId": "ping",
        "path": "/ping/",
        "some_future_server_field": "ignore me",
        "another_unknown": 42,
    })
    assert ep.operation_id == "ping"
    # No AttributeError, no ValidationError


# ─── FullEndpoint ─────────────────────────────────────────────────


def test_full_endpoint_inherits_and_extends():
    """FullEndpoint has all MinimalEndpoint fields plus parameters/request_schema/etc."""
    ep = FullEndpoint.model_validate({
        "operationId": "getSampleByUid",
        "path": "/nextseek_api/samples/{uid}/",
        "method": "GET",
        "description": "Retrieve one sample by UID",
        "tags": ["samples"],
        "parameters": {
            "uid": {"in": "path", "required": True, "schema": {"type": "string"}}
        },
        "request_schema": {},
        "response_schema": {"type": "object", "properties": {"uid": {"type": "string"}}},
        "examples": ["GET /samples/A1/"],
        "relevance_score": 0.87,
    })

    # MinimalEndpoint fields
    assert ep.operation_id == "getSampleByUid"
    assert ep.endpoint == "/nextseek_api/samples/{uid}/"
    assert ep.method == "GET"
    assert ep.tags == ["samples"]

    # FullEndpoint extensions
    assert ep.parameters["uid"]["required"] is True
    assert ep.request_schema == {}
    assert ep.response_schema is not None
    assert ep.examples == ["GET /samples/A1/"]
    assert ep.relevance_score == 0.87


def test_full_endpoint_relevance_score_bounds():
    """relevance_score must be between 0.0 and 1.0 (port of T2Viz ge=0, le=1)."""
    with pytest.raises(ValidationError):
        FullEndpoint.model_validate({
            "operationId": "x",
            "relevance_score": 1.5,
        })
    with pytest.raises(ValidationError):
        FullEndpoint.model_validate({
            "operationId": "x",
            "relevance_score": -0.1,
        })


# ─── SchemaRAGResponse + IngestResponse ───────────────────────────


def test_schema_rag_response_parses_minimal_endpoints():
    """SchemaRAGResponse with a list of MinimalEndpoint dicts parses correctly."""
    resp = SchemaRAGResponse.model_validate({
        "query": "find sample endpoints",
        "endpoints": [
            {"operationId": "getSamples", "path": "/samples/", "method": "GET"},
            {"operationId": "createSample", "path": "/samples/", "method": "POST"},
        ],
        "total_results": 2,
        "session_id": "sess-abc",
        "mode": "minimal",
    })
    assert resp.query == "find sample endpoints"
    assert resp.total_results == 2
    assert len(resp.endpoints) == 2
    assert resp.endpoints[0].operation_id == "getSamples"
    assert resp.endpoints[0].endpoint == "/samples/"


def test_ingest_response_parses():
    """IngestResponse has session_id, schema_url, ttl_minutes, expires_at, num_endpoints."""
    resp = IngestResponse.model_validate({
        "session_id": "sess-xyz",
        "schema_url": "https://nextseek.mit.edu/nextseek_api/openapi.json",
        "ttl_minutes": 30,
        "expires_at": "2026-04-09T12:00:00+00:00",
        "num_endpoints": 150,
    })
    assert resp.session_id == "sess-xyz"
    assert resp.schema_url == "https://nextseek.mit.edu/nextseek_api/openapi.json"
    assert resp.ttl_minutes == 30
    assert resp.num_endpoints == 150
    assert resp.expires_at.year == 2026


# ─── SessionState ─────────────────────────────────────────────────


def test_session_state_roundtrip(tmp_path):
    """Save + load preserves all SessionState fields via JSON."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(minutes=30)

    state = SessionState(
        session_id="sess-roundtrip",
        expires_at=expires,
        base_url="https://nextseek.mit.edu/nextseek_api",
        env_tag="prod",
        schema_url="https://nextseek.mit.edu/nextseek_api/openapi.json",
    )

    # Serialize to JSON and write to disk
    json_path = tmp_path / "session.json"
    json_path.write_text(state.model_dump_json())

    # Read back and reconstruct
    loaded = SessionState.model_validate_json(json_path.read_text())

    assert loaded.session_id == "sess-roundtrip"
    assert loaded.expires_at == expires
    assert loaded.base_url == "https://nextseek.mit.edu/nextseek_api"
    assert loaded.env_tag == "prod"
    assert loaded.schema_url == "https://nextseek.mit.edu/nextseek_api/openapi.json"


def test_session_state_is_expired():
    """is_expired() returns True for past expires_at, False for future."""
    past = SessionState(
        session_id="past",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        base_url="https://x",
        env_tag="dev",
        schema_url="https://x/openapi.json",
    )
    future = SessionState(
        session_id="future",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        base_url="https://x",
        env_tag="dev",
        schema_url="https://x/openapi.json",
    )

    assert past.is_expired() is True
    assert future.is_expired() is False


def test_session_state_env_tag_enum():
    """env_tag must be 'dev' or 'prod' — anything else fails validation."""
    with pytest.raises(ValidationError):
        SessionState(
            session_id="s",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            base_url="https://x",
            env_tag="staging",  # invalid
            schema_url="https://x/openapi.json",
        )


# ─── RequestSpec ──────────────────────────────────────────────────


def test_request_spec_validation():
    """Valid RequestSpec passes; missing operation_id or method fails."""
    valid = RequestSpec.model_validate({
        "operation_id": "getSampleByUid",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "A1"},
        "query_params": {},
        "request_body": {},
    })
    assert valid.operation_id == "getSampleByUid"
    assert valid.method == "GET"
    assert valid.path_params == {"uid": "A1"}

    # Missing operation_id
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({
            "method": "GET",
            "endpoint": "/samples/",
        })

    # Missing method
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({
            "operation_id": "getSamples",
            "endpoint": "/samples/",
        })

    # Missing endpoint
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({
            "operation_id": "getSamples",
            "method": "GET",
        })


def test_request_spec_method_must_be_nonempty_string():
    """RequestSpec.method must be a non-empty string (method allowlisting is
    handled by request_validator, not at the model layer — see task-06)."""
    with pytest.raises(ValidationError):
        RequestSpec.model_validate({
            "operation_id": "x",
            "method": "",
            "endpoint": "/x/",
        })
    # Any non-empty method string is accepted at the model layer
    for method in ["GET", "POST", "DELETE", "PATCH"]:
        spec = RequestSpec.model_validate({
            "operation_id": "x",
            "method": method,
            "endpoint": "/x/",
        })
        assert spec.method == method


def test_request_spec_default_param_dicts_are_empty():
    """path_params, query_params default to empty dicts; request_body defaults to None (CL-5)."""
    spec = RequestSpec.model_validate({
        "operation_id": "listSamples",
        "method": "GET",
        "endpoint": "/samples/",
    })
    assert spec.path_params == {}
    assert spec.query_params == {}
    assert spec.request_body is None  # CL-5: request_body is nullable, default None


def test_request_spec_roundtrip_json():
    """RequestSpec serializes and deserializes cleanly from JSON."""
    original = RequestSpec.model_validate({
        "operation_id": "createSample",
        "method": "POST",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {"project_id": "SRP"},
        "request_body": {"uid": "A1", "type": "tissue"},
    })
    dumped = original.model_dump_json()
    parsed = json.loads(dumped)
    assert parsed["method"] == "POST"
    assert parsed["request_body"]["uid"] == "A1"

    restored = RequestSpec.model_validate_json(dumped)
    assert restored == original


# ─── CL-5: RequestSpec headers + nullable request_body + extra=forbid ─


def test_request_spec_request_body_none_accepted():
    """Per CL-5: request_body=None is accepted (GET requests have no body)."""
    spec = RequestSpec(
        operation_id="x",
        method="GET",
        endpoint="/x/",
        request_body=None,
    )
    assert spec.request_body is None
    assert spec.method == "GET"


def test_request_spec_extra_field_rejected():
    """Per CL-5: extra='forbid' — passing path_template raises ValidationError."""
    with pytest.raises(ValidationError):
        RequestSpec(
            operation_id="x",
            method="GET",
            endpoint="/x/",
            path_template="/nextseek_api/samples/{uid}/",  # type: ignore[call-arg]
        )


def test_request_spec_headers_defaults_to_empty_dict():
    """Per CL-5: headers field present with default {}."""
    spec = RequestSpec(
        operation_id="x",
        method="GET",
        endpoint="/x/",
    )
    assert spec.headers == {}
    assert isinstance(spec.headers, dict)


# ─── CL-6: FullEndpoint.parameters union shape ────────────────────


def test_full_endpoint_parameters_accepts_list_form():
    """Per CL-6: FullEndpoint.parameters accepts the OpenAPI-native list form."""
    ep = FullEndpoint.model_validate({
        "operationId": "getSampleByUid",
        "path": "/nextseek_api/samples/{uid}/",
        "method": "GET",
        "parameters": [
            {"name": "uid", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
    })
    assert isinstance(ep.parameters, list)
    assert ep.parameters[0]["name"] == "uid"
    assert ep.parameters[0]["in"] == "path"


def test_full_endpoint_parameters_accepts_dict_form():
    """Per CL-6: FullEndpoint.parameters still accepts the legacy dict-keyed-by-name form."""
    ep = FullEndpoint.model_validate({
        "operationId": "getSampleByUid",
        "path": "/nextseek_api/samples/{uid}/",
        "method": "GET",
        "parameters": {
            "uid": {"in": "path", "required": True, "schema": {"type": "string"}}
        },
    })
    assert isinstance(ep.parameters, dict)
    assert ep.parameters["uid"]["in"] == "path"


# ─── DD-5: snake_case harmonization ───────────────────────────────


class TestSnakeCaseDump:
    """DD-5: canonical agent-visible surface is snake_case."""

    def test_minimal_endpoint_dumps_snake_case(self):
        e = MinimalEndpoint.model_validate({
            "operationId": "ListAssays",
            "path": "/nextseek_api/assays/",
            "method": "GET",
        })
        dumped = e.model_dump()
        assert "operation_id" in dumped
        assert "endpoint" in dumped
        assert "operationId" not in dumped
        assert "path" not in dumped
        assert dumped["operation_id"] == "ListAssays"
        assert dumped["endpoint"] == "/nextseek_api/assays/"

    def test_full_endpoint_round_trip(self):
        payload = {
            "operationId": "GetAssay",
            "path": "/nextseek_api/assays/{uid}/",
            "method": "GET",
            "parameters": [{"name": "uid", "in": "path", "required": True}],
            "request_schema": {},
            "response_schema": {"type": "object"},
            "examples": [],
            "description": "",
            "tags": [],
        }
        e = FullEndpoint.model_validate(payload)
        dumped = e.model_dump()
        # Round-trip: parse the snake_case dump and re-dump.
        reparsed = FullEndpoint.model_validate(dumped)
        assert reparsed.model_dump() == dumped
        assert "operation_id" in dumped
        assert "endpoint" in dumped
        assert "operationId" not in dumped
        assert "path" not in dumped
