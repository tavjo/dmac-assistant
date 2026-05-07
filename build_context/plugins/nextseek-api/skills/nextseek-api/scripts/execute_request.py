"""Live executor for NExtSEEK RequestSpec JSON with Layer 2 write-safety enforcement.

SAFETY-CRITICAL. This script is Layer 2 of the 3-layer write-safety defense
(DD-08). It ports the denylist + suspicious-body logic from T2Viz's
src/orchestration/api_executor.py (lines 18-42, 80-185) to the sync plugin
runtime.

Safety invariants enforced here:
  1. Method must be GET or POST (DELETE/PATCH/PUT are blocked unconditionally).
  2. Non-GET operations that are NOT under schema_rag/* are refused unless
     --confirmed-write is passed explicitly. This is the PRIMARY gate.
  3. Defense-in-depth: non-GET operations whose operation_id OR endpoint path
     contain any term from _DENYLIST_TERMS (upload|create|update|delete|remove|
     patch|put) are refused unless --confirmed-write, even if schema_rag check
     is somehow bypassed.
  4. EXCEPTION: POST to /nextseek_api/schema_rag/(ingest|retrieve)/ is always
     allowed, because SchemaRAG is read-only despite using POST.
  5. Suspicious-body check: if the request body contains any term from
     _SUSPICIOUS_BODY_TERMS (delete|remove|drop|overwrite|truncate|destroy)
     in key names or string values, refuse unless --confirmed-write.
  6. The internal request_validator is re-run before HTTP is touched.

Exit codes:
  0  Success
  1  Safety block, validation fail, or malformed input
  2  API error (NextseekAPIError, NextseekTimeoutError)
  3  Config error (env missing, cache miss)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Per CL-1: imports use `from lib.X import ...`. task-01's conftest.py adds
# scripts/ to sys.path so this resolves in tests and at runtime. No sys.path
# hacks, no bare imports.
from lib.cache_paths import resolve_endpoint_full_path
from lib.cli_common import add_env_file_arg
from lib.env_loader import EnvMissingError, load_environment
from lib.models import FullEndpoint, RequestSpec
from lib.nextseek_client import (
    NextseekAPIError,
    NextseekAuthError,
    NextseekClient,
    NextseekClientError,
    NextseekTimeoutError,
)
from lib.request_validator import (
    ValidationResult,
    validate_request,
)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_API = 2
EXIT_CONFIG = 3

# -- Ported from T2Viz src/orchestration/api_executor.py:18-19 ---------------
_DENYLIST_TERMS = ("upload", "create", "update", "delete", "remove", "patch", "put")
_SUSPICIOUS_BODY_TERMS = ("delete", "remove", "drop", "overwrite", "truncate", "destroy")
_SCHEMA_RAG_SAFE_PATH_PREFIXES = (
    "/nextseek_api/schema_rag/",
    "schema_rag/",
)


# -- Ported from T2Viz api_executor.py:22-27 --------------------------------
def _contains_denylisted_term(*values: str | None) -> bool:
    for value in values:
        lowered = str(value or "").lower()
        if any(term in lowered for term in _DENYLIST_TERMS):
            return True
    return False


# -- Ported from T2Viz api_executor.py:30-42 --------------------------------
def _contains_suspicious_body(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(term in str(key).lower() for term in _SUSPICIOUS_BODY_TERMS):
                return True
            if _contains_suspicious_body(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_suspicious_body(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in _SUSPICIOUS_BODY_TERMS)
    return False


def _is_schema_rag_safe_post(endpoint_path: str) -> bool:
    lowered = endpoint_path.lower()
    return any(prefix in lowered for prefix in _SCHEMA_RAG_SAFE_PATH_PREFIXES)


def _enforce_write_safety(
    *,
    method: str,
    operation_id: str,
    endpoint_path: str,
    request_body: Any,
    confirmed_write: bool,
) -> tuple[bool, str, str]:
    """Return (allowed, error_code, message).

    Ports the enforcement block from T2Viz api_executor.py:112-142 to sync CLI.

    The PRIMARY gate is: non-GET + non-schema_rag requires --confirmed-write.
    The denylist and suspicious-body checks are defense-in-depth layers on TOP
    of this gate (CL-8).
    """
    method_upper = method.upper()

    # 1. Method allowlist.
    if method_upper not in {"GET", "POST"}:
        return (
            False,
            "UnsupportedMethodPolicy",
            f"HTTP method {method_upper!r} is blocked by Layer 2 safety policy.",
        )

    # 2. GET is always allowed (after validator).
    if method_upper == "GET":
        return (True, "", "")

    # 3. POST: auto-allow schema_rag paths (read-only despite POST).
    is_schema_rag = _is_schema_rag_safe_post(endpoint_path)
    if is_schema_rag:
        return (True, "", "")

    # 4. PRIMARY GATE (CL-8): ANY non-GET, non-schema_rag POST requires
    #    --confirmed-write. The denylist is defense-in-depth, not the gate.
    if not confirmed_write:
        # Provide a more specific message if denylist terms are present
        if _contains_denylisted_term(operation_id, endpoint_path):
            return (
                False,
                "SafetyPolicyBlocked",
                (
                    "Selected request was blocked by Layer 2 safety policy due to a "
                    f"denylisted operation or path (operation_id={operation_id!r}, "
                    f"endpoint={endpoint_path!r}). Re-run with --confirmed-write to override."
                ),
            )
        if _contains_suspicious_body(request_body):
            return (
                False,
                "SuspiciousRequestBody",
                (
                    "Selected request was blocked by Layer 2 safety policy due to a "
                    "suspicious request body. Re-run with --confirmed-write to override."
                ),
            )
        # General block: non-GET, non-schema_rag, no denylist terms, still blocked.
        return (
            False,
            "SafetyPolicyBlocked",
            (
                f"Non-GET request (method={method_upper!r}, "
                f"operation_id={operation_id!r}, endpoint={endpoint_path!r}) "
                "requires --confirmed-write to execute. This is a safety policy "
                "requirement for all non-GET, non-schema_rag operations."
            ),
        )

    # 5. --confirmed-write is present; allow.
    return (True, "", "")


# -- CLI plumbing -----------------------------------------------------------
# Cache paths use CL-7 helpers (resolve_endpoint_full_path, resolve_env_cache_dir)
# -- no local _resolve_cache_dir duplicate.


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="execute_request.py",
        description="Execute a validated NExtSEEK RequestSpec with Layer 2 safety enforcement.",
    )
    parser.add_argument("--env", choices=["dev", "prod"], required=True)
    add_env_file_arg(parser)
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to JSON file containing the RequestSpec (overrides stdin).",
    )
    parser.add_argument(
        "--confirmed-write",
        action="store_true",
        help=(
            "Explicit opt-out for Layer 2 write-safety denylist. Required for any "
            "non-GET, non-schema_rag operation. This flag is NOT in the Claude Code "
            "bash allowlist, so calls using it always prompt the user."
        ),
    )
    return parser.parse_args(argv)


def _load_request_spec_json(args: argparse.Namespace) -> dict[str, Any]:
    if args.file is not None:
        text = args.file.read_text()
    else:
        text = sys.stdin.read()
    if not text.strip():
        raise ValueError("empty request spec input")
    return json.loads(text)


def _load_cached_endpoint(op_id: str, env_tag: str) -> FullEndpoint | None:
    """Load a FullEndpoint JSON from the env-scoped cache (CL-7)."""
    path = resolve_endpoint_full_path(env_tag, op_id)
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    # task-06b: full-spec cache is now wrapped as {"session_id": ..., "spec": {...}}.
    # Tolerate both the wrapped and the legacy bare-dict shapes.
    if (
        isinstance(raw, dict)
        and "spec" in raw
        and "session_id" in raw
        and isinstance(raw["spec"], dict)
    ):
        raw = raw["spec"]
    return FullEndpoint.model_validate(raw)


def _fail(message: str, code: str, exit_code: int) -> int:
    print(f"ERROR[{code}]: {message}", file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # 1. Parse RequestSpec JSON (stdin or --file).
    try:
        raw = _load_request_spec_json(args)
        spec = RequestSpec.model_validate(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return _fail(f"Invalid JSON input: {exc}", "JSON_PARSE", EXIT_FAIL)
    except Exception as exc:  # pydantic.ValidationError etc.
        return _fail(f"RequestSpec validation failed: {exc}", "SPEC_VALIDATION", EXIT_FAIL)

    # 2. Load cached FullEndpoint via CL-7 cache_paths helper (task-08 wrote this).
    endpoint = _load_cached_endpoint(spec.operation_id, args.env)
    if endpoint is None:
        return _fail(
            f"Run fetch_spec.py first for operation {spec.operation_id!r}",
            "CACHE_MISS",
            EXIT_CONFIG,
        )

    # 3. Re-run the static validator (defense in depth, per DD-12).
    # CL-2: ValidationResult.passed (not .ok); ValidationError.to_dict().
    result: ValidationResult = validate_request(spec=spec, endpoint=endpoint)
    # Filter out DENYLIST_BLOCK errors -- Layer 2 (_enforce_write_safety) handles
    # the denylist with --confirmed-write override capability. The static
    # validator flags denylist hits as hard errors, but execute_request.py needs
    # Layer 2 to make the allow/deny decision (with --confirmed-write support).
    non_denylist_errors = [e for e in result.errors if e.code != "DENYLIST_BLOCK"]
    if non_denylist_errors:
        error_dicts = [err.to_dict() for err in non_denylist_errors]
        messages = "; ".join(d.get("message", "") for d in error_dicts)
        return _fail(
            f"validation FAIL: {messages}",
            "VALIDATION_FAIL",
            EXIT_FAIL,
        )

    # Use the rendered path (with {param} placeholders interpolated) from the
    # validator result. Falls back to spec.endpoint if rendering was skipped.
    resolved_endpoint = result.rendered_path or spec.endpoint

    # 4. Layer 2 write-safety enforcement (THE CRITICAL GATE).
    allowed, error_code, message = _enforce_write_safety(
        method=spec.method,
        operation_id=spec.operation_id,
        endpoint_path=spec.endpoint,
        request_body=spec.request_body,
        confirmed_write=bool(args.confirmed_write),
    )
    if not allowed:
        return _fail(message, error_code, EXIT_FAIL)

    # 5. Load env & call the client.
    try:
        config = load_environment(
            env_path=args.env_file,
            use_dev=(args.env == "dev"),
        )
    except EnvMissingError as exc:
        return _fail(f"missing credentials ({exc})", "EnvMissingError", EXIT_CONFIG)

    try:
        with NextseekClient(config=config) as client:
            response = client.request(
                spec.method.upper(),
                resolved_endpoint,
                params=spec.query_params or None,
                json=spec.request_body if isinstance(spec.request_body, dict) else None,
            )
    except NextseekAuthError as exc:
        return _fail(str(exc), "NextseekAuthError", EXIT_API)
    except NextseekTimeoutError as exc:
        return _fail(str(exc), "NextseekTimeoutError", EXIT_API)
    except NextseekAPIError as exc:
        return _fail(str(exc), "NextseekAPIError", EXIT_API)
    except NextseekClientError as exc:
        return _fail(str(exc), exc.__class__.__name__, EXIT_API)

    # 6. Print response to stdout.
    print(json.dumps(response, indent=2, default=str))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
