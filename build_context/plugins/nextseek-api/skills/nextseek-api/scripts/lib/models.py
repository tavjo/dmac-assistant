"""Pydantic v2 models for the nextseek-api plugin.

Ported from T2Viz's src/schemas/schema_rag.py (lines 15-105) for
MinimalEndpoint, FullEndpoint, SchemaRAGResponse, IngestResponse — with
additions for SessionState (on-disk session.json format) and RequestSpec
(the JSON-over-stdin input format described in DD-11).

Pydantic config for all aliased models:
    ConfigDict(extra="ignore", populate_by_name=True)

- extra="ignore": unknown fields on the wire are silently dropped so
  server-side schema additions don't break the client. (Phase 2B.9.1)
- populate_by_name=True: both the wire alias (e.g. `operationId`, `path`)
  and the python attr (`operation_id`, `endpoint`) are accepted as input.

Canonical output is snake_case (DD-5). All downstream serializers dump
with ``model_dump(by_alias=False)`` so the agent-visible surface is
harmonized on snake_case. ``by_alias=True`` is only used for interop
with server OpenAPI wire format (the camelCase shape), which the
plugin accepts via ``populate_by_name=True`` but never re-emits.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ─── SchemaRAG endpoint models (ported from T2Viz) ────────────────


class MinimalEndpoint(BaseModel):
    """Lightweight endpoint representation for first-pass retrieval.

    Ported verbatim from T2Viz schema_rag.py:15-30.
    Used when mode='minimal' is requested from the SchemaRAG service.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    operation_id: str = Field(
        ...,
        alias="operationId",
        description="Unique operation identifier from OpenAPI spec",
    )
    endpoint: str = Field(
        "",
        alias="path",
        description="API endpoint path, e.g. /nextseek_api/samples/",
    )
    method: str = Field("GET", description="HTTP method: GET, POST, PATCH, DELETE")
    description: str = Field("", description="Human-readable endpoint description")
    tags: list[str] = Field(default_factory=list, description="OpenAPI tags for grouping")


class FullEndpoint(MinimalEndpoint):
    """Complete endpoint with schema details for query construction.

    Ported verbatim from T2Viz schema_rag.py:33-54.
    Extends MinimalEndpoint with parameter definitions, request body
    schema, examples, and a server-computed relevance score.
    """

    parameters: list[dict[str, Any]] | dict[str, dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Path/query/header parameter definitions. Per CL-6, accepts BOTH "
            "the OpenAPI-native list form (list[dict]) AND the legacy dict-keyed-by-name "
            "form (dict[str, dict]). task-06's validator normalizes list -> dict."
        ),
    )
    request_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Request body JSON schema",
    )
    response_schema: dict[str, Any] | None = Field(
        default=None,
        description="Response body JSON schema",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Example request/response snippets",
    )
    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Server-computed relevance to query",
    )


class SchemaRAGResponse(BaseModel):
    """Response from SchemaRAG retrieve endpoint.

    Ported verbatim from T2Viz schema_rag.py:76-89.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query: str = Field(..., description="Original query string")
    endpoints: list[MinimalEndpoint] | list[FullEndpoint] = Field(
        ..., description="Ranked endpoint results"
    )
    total_results: int = Field(..., description="Total number of matched endpoints")
    session_id: str | None = Field(
        default=None, description="Server session ID for cache reuse"
    )
    mode: str | None = Field(default=None, description="Retrieval mode used")


class IngestResponse(BaseModel):
    """Response from SchemaRAG ingest endpoint.

    Ported verbatim from T2Viz schema_rag.py:92-105.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    session_id: str = Field(
        ..., description="Reusable session ID for subsequent retrieve calls"
    )
    schema_url: str = Field(..., description="URL of the ingested OpenAPI schema")
    ttl_minutes: int = Field(..., description="Session time-to-live in minutes")
    expires_at: datetime = Field(..., description="Absolute expiration timestamp")
    num_endpoints: int = Field(
        ..., description="Number of endpoints parsed from schema"
    )


# ─── Plugin-specific models (new in nextseek-api) ─────────────────


class SessionState(BaseModel):
    """On-disk session.json format for the plugin's persistent cache.

    One of these lives at ~/.cache/nextseek-api/{env_tag}/session.json
    per env (dev / prod). Task-05 (SchemaRAG client) writes + reads it;
    task-07 (init_session.py) creates it on bootstrap.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    session_id: str = Field(..., description="SchemaRAG session ID from ingest")
    expires_at: datetime = Field(
        ..., description="UTC timestamp when the session becomes invalid"
    )
    base_url: str = Field(..., description="Resolved NExtSEEK base URL")
    env_tag: Literal["dev", "prod"] = Field(
        ..., description="Which environment this session belongs to"
    )
    schema_url: str = Field(..., description="OpenAPI schema URL used by SchemaRAG ingest")

    def is_expired(self) -> bool:
        """Return True if the session is past its expires_at timestamp.

        Compares against datetime.now(timezone.utc). Naive datetimes in
        expires_at are treated as UTC.
        """
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires


class RequestSpec(BaseModel):
    """JSON-over-stdin request spec for validate_request.py / execute_request.py.

    Shape defined in DD-11 + CL-5:
        {
          "operation_id": "...",
          "method": "GET" | "POST",
          "endpoint": "/nextseek_api/samples/{uid}/",
          "path_params": {"uid": "A1"},
          "query_params": {"project_id": "SRP"},
          "headers": {"X-Custom": "value"},
          "request_body": null  # or {...} for POST
        }

    Method is constrained to GET/POST via Literal — PATCH/PUT/DELETE fail
    at the pydantic layer before any downstream script can send them.

    Per CL-5:
    - `model_config = ConfigDict(extra="forbid")` — unknown fields like
      `path_template` raise ValidationError instead of being silently dropped.
    - `request_body: dict | None = None` — GET requests may pass None.
    - `headers: dict[str, str] = {}` — present so task-06's validator can
      iterate header-type parameters.
    """

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(
        ..., min_length=1, description="OpenAPI operation identifier"
    )
    method: str = Field(
        ..., min_length=1, description="HTTP method (validated by request_validator, not at model level)"
    )
    endpoint: str = Field(
        ..., min_length=1, description="Endpoint path (may contain {param} placeholders)"
    )
    path_params: dict[str, Any] = Field(
        default_factory=dict, description="Path parameter values to interpolate"
    )
    query_params: dict[str, Any] = Field(
        default_factory=dict, description="Query string parameters"
    )
    headers: dict[str, str] = Field(
        default_factory=dict, description="HTTP headers (for header-type parameters)"
    )
    request_body: dict[str, Any] | None = Field(
        default=None, description="JSON request body (None for GET; dict for POST)"
    )
