"""Static request validator: pre-flight checks with zero network I/O.

Validates a RequestSpec against a cached FullEndpoint, running seven
mechanical checks before any HTTP call is attempted. This module is
imported by both validate_request.py (task-09, the user-facing CLI)
and execute_request.py (task-10, defense-in-depth re-check).

Design decisions:
  - Pure function. No httpx. No state. No I/O except (optional) logging.
  - Errors accumulate — one call returns ALL problems, not just the first.
  - Denylist is case-insensitive and only applies to non-GET requests.
  - schema_rag/ paths are whitelisted from the denylist (plugin invariant).

References:
  - T2Viz src/orchestration/api_executor.py lines 18-52 — path rendering
    and denylist idiom.
  - Plan DD-12 for the full check list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from lib.models import FullEndpoint, RequestSpec

# Case-insensitive denylist applied to operation_id + path for non-GET requests.
# Mirrors T2Viz _DENYLIST_TERMS in src/orchestration/api_executor.py:18.
_DENYLIST_TERMS: tuple[str, ...] = (
    "upload",
    "create",
    "update",
    "delete",
    "remove",
    "patch",
    "put",
)

# Allowed HTTP methods for the plugin. DD-12 restricts to read-ish verbs.
_ALLOWED_METHODS: frozenset[str] = frozenset({"GET", "POST"})

# Paths whitelisted from the denylist (schema discovery is always safe).
# DD-08 Layer 2.
_SCHEMA_RAG_WHITELIST_PREFIXES: tuple[str, ...] = (
    "schema_rag/",
    "/schema_rag/",
    "/nextseek_api/schema_rag/",
)

# T2Viz path-template regex — simple non-nested {name} placeholders.
_PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")


# ---------------------------------------------------------------------------
# task-03 #15: humanized pydantic errors for RequestSpec input validation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldError:
    """One humanized pydantic validation failure.

    - ``location``: JSONPath-ish pointer (``$.operationId``).
    - ``code``: pydantic ``type`` (``extra_forbidden``, ``missing``, ...).
    - ``message``: pydantic ``msg``.
    - ``hint``: optional actionable hint (e.g. ``did you mean 'operation_id'?``).
    """

    location: str
    code: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``json.dumps``."""
        return {
            "location": self.location,
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
        }


# Known camelCase → snake_case (or renamed) field hints for RequestSpec.
# Mapping: wire-name -> (canonical-snake-name, human hint string).
_SNAKE_HINTS: dict[str, tuple[str, str]] = {
    "operationId": (
        "operation_id",
        "did you mean 'operation_id'? RequestSpec uses snake_case.",
    ),
    "requestBody": (
        "request_body",
        "did you mean 'request_body'? RequestSpec uses snake_case.",
    ),
    "pathParams": (
        "path_params",
        "did you mean 'path_params'? RequestSpec uses snake_case.",
    ),
    "queryParams": (
        "query_params",
        "did you mean 'query_params'? RequestSpec uses snake_case.",
    ),
    "path": (
        "endpoint",
        "the field is named 'endpoint', not 'path'.",
    ),
    "body": (
        "request_body",
        "the field is named 'request_body', not 'body'.",
    ),
}


def humanize_validation_error(exc: PydanticValidationError) -> list[FieldError]:
    """Flatten a pydantic ``ValidationError`` to humanized ``FieldError`` list.

    - Builds a JSONPath-ish ``location`` from the ``loc`` tuple.
    - Preserves the pydantic ``type`` as ``code`` and ``msg`` as ``message``.
    - When the offending field appears in ``_SNAKE_HINTS``, attaches an
      actionable hint (camelCase → snake_case, or renamed fields).
    """
    out: list[FieldError] = []
    for err in exc.errors():
        loc_parts = [str(x) for x in err.get("loc", ())]
        location = "$." + ".".join(loc_parts) if loc_parts else "$"
        code = str(err.get("type", "validation_error"))
        message = str(err.get("msg", "validation failed"))
        hint: str | None = None
        head = loc_parts[0] if loc_parts else ""
        if head in _SNAKE_HINTS:
            _, hint = _SNAKE_HINTS[head]
        out.append(
            FieldError(location=location, code=code, message=message, hint=hint)
        )
    return out


@dataclass(frozen=True)
class ValidationError:
    """One validation failure with a machine-readable code and human message.

    CL-2: exposes `to_dict()` for serialization by downstream CLIs
    (task-09 validate_request.py, task-10 execute_request.py).
    """

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return `{"code": ..., "message": ...}` for JSON serialization."""
        return {"code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    """Aggregate result of validate_request().

    CL-2: field is `passed` (not `ok`). Consumers in task-09 and task-10
    check `if not result.passed:` — do not rename.

    Attributes:
        passed: True if zero errors accumulated.
        rendered_path: The path template after interpolating path_params, or
            None if path rendering itself failed.
        errors: List of all errors found (not just the first).
    """

    passed: bool
    rendered_path: str | None = None
    errors: list[ValidationError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_request(spec: RequestSpec, endpoint: FullEndpoint) -> ValidationResult:
    """Run all static checks against a constructed request.

    Returns a ValidationResult carrying every error found. Caller decides
    exit code / CLI output.
    """
    errors: list[ValidationError] = []

    # --- Check 1: path template rendering ---
    rendered_path, render_err = _render_path(endpoint.endpoint, spec.path_params)
    if render_err is not None:
        errors.append(render_err)

    # --- Check 2: method alignment ---
    spec_method = (spec.method or "").upper()
    endpoint_method = (endpoint.method or "").upper()
    if spec_method != endpoint_method:
        errors.append(
            ValidationError(
                code="METHOD_MISMATCH",
                message=(
                    f"Request method {spec_method!r} does not match endpoint "
                    f"method {endpoint_method!r} for operation "
                    f"{endpoint.operation_id!r}."
                ),
            )
        )

    # --- Check 3: endpoint path alignment (template form, before rendering) ---
    if spec.endpoint != endpoint.endpoint:
        errors.append(
            ValidationError(
                code="ENDPOINT_PATH_MISMATCH",
                message=(
                    f"Request endpoint {spec.endpoint!r} does not match the "
                    f"cached endpoint path {endpoint.endpoint!r} for operation "
                    f"{endpoint.operation_id!r}."
                ),
            )
        )

    # --- Check 4: required query/header parameters present ---
    errors.extend(_check_required_params(spec, endpoint))

    # --- Check 5: required body fields present ---
    errors.extend(_check_required_body_fields(spec, endpoint))

    # --- Check 6: method allowlist ---
    if spec_method and spec_method not in _ALLOWED_METHODS:
        errors.append(
            ValidationError(
                code="UNSUPPORTED_METHOD",
                message=(
                    f"HTTP method {spec_method!r} is not in the plugin "
                    f"allowlist {sorted(_ALLOWED_METHODS)!r}."
                ),
            )
        )

    # --- Check 7: denylist (non-GET, non-schema_rag) ---
    if spec_method and spec_method != "GET":
        if not _is_schema_rag_whitelisted(endpoint.endpoint):
            if _contains_denylisted_term(spec.operation_id, endpoint.endpoint):
                errors.append(
                    ValidationError(
                        code="DENYLIST_BLOCK",
                        message=(
                            f"Non-GET request for operation "
                            f"{spec.operation_id!r} on path {endpoint.endpoint!r} "
                            f"matches a denylisted term "
                            f"({', '.join(_DENYLIST_TERMS)}) and was blocked."
                        ),
                    )
                )

    return ValidationResult(
        passed=not errors,
        rendered_path=rendered_path,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_path(
    template: str,
    path_params: dict[str, Any],
) -> tuple[str | None, ValidationError | None]:
    """Interpolate {name} placeholders in template using path_params.

    Returns (rendered_path, None) on success or (None, error) on first
    missing key. Mirrors T2Viz _render_endpoint() logic.
    """
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in path_params:
            missing.append(key)
            return match.group(0)
        return str(path_params[key])

    rendered = _PATH_PARAM_RE.sub(_replace, template)

    if missing:
        unique = ", ".join(sorted(set(missing)))
        return None, ValidationError(
            code="MISSING_PATH_PARAM",
            message=f"Path template {template!r} requires path_params: {unique}.",
        )
    return rendered, None


def _normalize_parameters(
    params: list[dict[str, Any]] | dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Normalize OpenAPI parameters to a dict keyed by name.

    CL-6: FullEndpoint.parameters accepts both the OpenAPI-native list form
    (`[{"name": "uid", "in": "path", ...}]`) and the dict-keyed-by-name form
    (`{"uid": {"in": "path", ...}}`). The validator normalizes the list form
    into the dict form at entry so the rest of the code can iterate
    `params.items()` uniformly.
    """
    if isinstance(params, dict):
        return params
    if isinstance(params, list):
        return {
            p["name"]: p
            for p in params
            if isinstance(p, dict) and "name" in p
        }
    return {}


def _check_required_params(
    spec: RequestSpec,
    endpoint: FullEndpoint,
) -> list[ValidationError]:
    """Walk endpoint.parameters; ensure every required one is present.

    Each entry has an 'in' field ('query', 'header', 'path') and an optional
    'required' bool. Query-type parameters must be in spec.query_params;
    header-type parameters must be in spec.headers (CL-5 adds the headers
    field to RequestSpec). Path-type parameters are enforced upstream by
    _render_path (which emits MISSING_PATH_PARAM).

    CL-6: parameters may arrive as a list OR a dict — normalized via
    _normalize_parameters before iteration.
    """
    errors: list[ValidationError] = []
    params = _normalize_parameters(endpoint.parameters)
    if not params:
        return errors

    for name, meta in params.items():
        if not isinstance(meta, dict):
            continue
        if not meta.get("required", False):
            continue
        location = str(meta.get("in", "query")).lower()
        if location == "query":
            if name not in (spec.query_params or {}):
                errors.append(
                    ValidationError(
                        code="MISSING_REQUIRED_PARAM",
                        message=(
                            f"Required query parameter {name!r} for operation "
                            f"{endpoint.operation_id!r} is missing from query_params."
                        ),
                    )
                )
        elif location == "header":
            # CL-5: spec.headers is a dict[str, str] on RequestSpec. CL-6
            # ensures this branch is reachable when parameters is a list.
            if name not in (spec.headers or {}):
                errors.append(
                    ValidationError(
                        code="MISSING_HEADER",
                        message=(
                            f"Required header {name!r} for operation "
                            f"{endpoint.operation_id!r} is missing from spec.headers."
                        ),
                    )
                )
        # 'path' location is enforced by _render_path (MISSING_PATH_PARAM).
    return errors


def _check_required_body_fields(
    spec: RequestSpec,
    endpoint: FullEndpoint,
) -> list[ValidationError]:
    """Validate that all fields in request_schema['required'] exist in request_body."""
    errors: list[ValidationError] = []
    schema = endpoint.request_schema or {}
    if not isinstance(schema, dict):
        return errors
    required = schema.get("required") or []
    if not required:
        return errors

    body = spec.request_body if isinstance(spec.request_body, dict) else {}
    for field_name in required:
        if field_name not in body:
            errors.append(
                ValidationError(
                    code="MISSING_REQUIRED_BODY_FIELD",
                    message=(
                        f"Required request body field {field_name!r} for "
                        f"operation {endpoint.operation_id!r} is missing."
                    ),
                )
            )
    return errors


def _contains_denylisted_term(*values: str | None) -> bool:
    """Case-insensitive substring check. Mirrors T2Viz api_executor.py:22-27."""
    for value in values:
        lowered = str(value or "").lower()
        if any(term in lowered for term in _DENYLIST_TERMS):
            return True
    return False


def _is_schema_rag_whitelisted(path: str) -> bool:
    """True if the endpoint path is under schema_rag/ (always-safe)."""
    if not path:
        return False
    normalized = path.strip().lower()
    return any(
        normalized.startswith(prefix) for prefix in _SCHEMA_RAG_WHITELIST_PREFIXES
    )
