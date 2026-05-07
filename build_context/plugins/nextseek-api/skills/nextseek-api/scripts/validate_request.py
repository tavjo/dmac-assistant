"""Static validator for NExtSEEK RequestSpec JSON.

Reads a RequestSpec (stdin or --file), loads the matching FullEndpoint from
the local cache, runs the shared request_validator, and emits a structured
result. No live HTTP call is made.

Failure output shape (task-03 #13/#15):
    {"ok": false, "errors": [{"location", "code", "message", "hint"}, ...]}

Success output shape:
    {"ok": true, "status": "PASS", "spec": {...}}

Exit codes:
  0  PASS
  1  FAIL (validation error, denylist block, or JSON parse error)
  2  Cache miss (run fetch_spec.py first)
  3  Config error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Per CL-1: imports use `from lib.X import ...`. task-01's conftest.py adds
# scripts/ to sys.path so this resolves in tests and at runtime.
from lib.cache_paths import resolve_endpoint_full_path
from lib.cli_common import add_env_file_arg
from lib.models import FullEndpoint, RequestSpec
from lib.request_validator import (
    FieldError,
    ValidationResult,
    humanize_validation_error,
    validate_request,
)
from pydantic import ValidationError as PydanticValidationError

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CACHE_MISS = 2
EXIT_CONFIG = 3


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_request.py",
        description="Statically validate a NExtSEEK request spec against a cached endpoint.",
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
        "--json",
        action="store_true",
        help=(
            "Emit failure output as structured JSON (this is the default "
            "shape — the flag is kept for explicit opt-in documentation)."
        ),
    )
    return parser.parse_args(argv)


def _load_request_spec_json(args: argparse.Namespace) -> dict[str, Any]:
    """Load raw JSON dict from --file (if provided) or stdin."""
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
    # Tolerate both the wrapped shape AND the legacy bare-dict shape so that
    # pre-existing fixtures and hand-written caches keep working.
    if (
        isinstance(raw, dict)
        and "spec" in raw
        and "session_id" in raw
        and isinstance(raw["spec"], dict)
    ):
        raw = raw["spec"]
    return FullEndpoint.model_validate(raw)


def _emit_fail(errors: list[dict[str, Any]]) -> int:
    """Print structured failure JSON to stdout and return EXIT_FAIL.

    Unified shape (task-03): ``{"ok": false, "errors": [...]}``.
    """
    print(json.dumps({"ok": False, "errors": errors}, indent=2))
    return EXIT_FAIL


def _fielderrors_to_dicts(errors: list[FieldError]) -> list[dict[str, Any]]:
    return [e.to_dict() for e in errors]


def _result_to_error_dicts(result: ValidationResult) -> list[dict[str, Any]]:
    """Serialize ValidationResult.errors to the unified {location,code,message,hint} shape.

    Static-validator errors (from request_validator.validate_request) do not
    have location/hint fields, so we synthesize a top-level ``$`` location and
    leave ``hint`` as None to keep the output shape consistent with
    humanized pydantic errors.
    """
    out: list[dict[str, Any]] = []
    for err in result.errors:
        out.append(
            {
                "location": "$",
                "code": err.code,
                "message": err.message,
                "hint": None,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns an exit code (0, 1, 2, or 3)."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # 1. Parse RequestSpec JSON.
    try:
        raw = _load_request_spec_json(args)
    except (ValueError, json.JSONDecodeError) as exc:
        return _emit_fail(
            [
                {
                    "location": "$",
                    "code": "JSON_PARSE",
                    "message": f"Invalid request spec JSON: {exc}",
                    "hint": None,
                }
            ]
        )

    try:
        spec = RequestSpec.model_validate(raw)
    except PydanticValidationError as exc:
        humanized = humanize_validation_error(exc)
        return _emit_fail(_fielderrors_to_dicts(humanized))

    # 2. Look up the cached FullEndpoint (CL-7 cache_paths helpers).
    endpoint = _load_cached_endpoint(spec.operation_id, args.env)
    if endpoint is None:
        expected = resolve_endpoint_full_path(args.env, spec.operation_id)
        print(
            f"ERROR: Run fetch_spec.py first for operation {spec.operation_id!r} "
            f"(missing {expected})",
            file=sys.stderr,
        )
        return EXIT_CACHE_MISS

    # 3. Run the shared validator (CL-6: validator normalizes parameters internally).
    result: ValidationResult = validate_request(spec=spec, endpoint=endpoint)

    # CL-2: field is `passed` (not `ok`).
    if result.passed:
        payload = {
            "ok": True,
            "status": "PASS",
            "spec": spec.model_dump(mode="json"),
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    return _emit_fail(_result_to_error_dicts(result))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
