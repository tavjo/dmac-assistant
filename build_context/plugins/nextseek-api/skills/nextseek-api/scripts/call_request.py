"""Unified nextseek-call CLI: resolve op -> build RequestSpec -> validate -> execute.

Ergonomic entry point for the 80% happy path (Issue #7). Agents give an
``--op`` (exact operation_id OR natural-language query) plus flat
``--path-params / --query-params / --body`` JSON flags and get back the live
response — no hand-written RequestSpec JSON needed. Raw RequestSpec JSON is
still accepted via ``--spec FILE`` / ``--spec -`` for advanced use.

Exit codes:
  0  success (including --dry-run OK)
  1  top-level / unexpected failure
  2  no operation matches
  3  ambiguous --op (>1 hits); listing printed to stderr
  4  static validation failed
  5  non-GET without --confirmed-write
  6  API / network error
  7  config / session / env error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# CL-1: import via `from lib.X import ...`; conftest.py inserts scripts/ onto path.
from lib.cache_paths import resolve_plugin_cache_base
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
from lib.pagination import PageEnvelope, paginate
from lib.request_validator import validate_request
from lib.schema_rag_client import SchemaRAGClient

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NO_MATCH = 2
EXIT_AMBIGUOUS = 3
EXIT_VALIDATION = 4
EXIT_CONFIRM_REQUIRED = 5
EXIT_API = 6
EXIT_CONFIG = 7


# ---------------------------------------------------------------------------
# Flag-value loading
# ---------------------------------------------------------------------------


def _load_json_arg(value: str | None) -> Any:
    """Parse a flag value as literal JSON or ``@file.json``.

    Returns ``None`` when value is falsy.
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if s.startswith("@"):
        path = Path(s[1:]).expanduser()
        return json.loads(path.read_text())
    return json.loads(s)


# ---------------------------------------------------------------------------
# Operation resolution
# ---------------------------------------------------------------------------


def resolve_operation(
    op_arg: str,
    rag: SchemaRAGClient,
    env_tag: str,
    session_id: str,
    *,
    cache_base: Path | None = None,
) -> dict[str, Any]:
    """Resolve ``op_arg`` to a full endpoint dict.

    Strategy:
      1. Try exact operation_id via ``fetch_spec._lazy_fetch_full``.
      2. On ``LookupError``, fall back to a minimal NL retrieve.
         * 0 hits -> ``SystemExit(EXIT_NO_MATCH)``
         * >1 hits -> print candidates, ``SystemExit(EXIT_AMBIGUOUS)``
         * 1 hit  -> lazy-fetch the resolved operation_id.
    """
    # Import lazily to avoid a circular dep at module load (fetch_spec imports
    # are otherwise fine; this keeps the module surface minimal).
    from fetch_spec import _lazy_fetch_full

    try:
        return _lazy_fetch_full(
            op_arg, rag, env_tag, session_id, cache_base=cache_base
        )
    except LookupError:
        pass

    # Fallback: natural-language minimal retrieve to surface candidates.
    resp = rag.retrieve_with_auto_ingest(op_arg, mode="minimal", top_k=5)
    hits = list(resp.endpoints)
    if not hits:
        print(
            f"ERROR: no operation matches {op_arg!r}",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_NO_MATCH)
    if len(hits) > 1:
        print(
            f"ERROR: multiple matches for --op {op_arg!r}; "
            f"re-run with an exact operation_id:",
            file=sys.stderr,
        )
        for ep in hits:
            desc = getattr(ep, "description", "") or ""
            print(f"  {ep.operation_id}: {desc}", file=sys.stderr)
        raise SystemExit(EXIT_AMBIGUOUS)

    resolved_op_id = hits[0].operation_id
    return _lazy_fetch_full(
        resolved_op_id, rag, env_tag, session_id, cache_base=cache_base
    )


# ---------------------------------------------------------------------------
# RequestSpec construction
# ---------------------------------------------------------------------------


def build_spec(
    op: dict[str, Any],
    *,
    path_params: dict[str, Any] | None,
    query_params: dict[str, Any] | None,
    body: dict[str, Any] | None,
) -> RequestSpec:
    """Construct a RequestSpec from a resolved full endpoint dict + flat flags."""
    return RequestSpec(
        operation_id=str(op.get("operation_id") or ""),
        method=str(op.get("method") or "GET").upper(),
        endpoint=str(op.get("endpoint") or ""),
        path_params=dict(path_params or {}),
        query_params=dict(query_params or {}),
        headers={},
        request_body=body,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="call_request.py",
        description=(
            "Unified NExtSEEK call: resolve op, build RequestSpec from flags, "
            "validate, and execute in one step."
        ),
    )
    parser.add_argument("--env", choices=["dev", "prod"], default="prod")
    add_env_file_arg(parser)
    parser.add_argument(
        "--op",
        help="operation_id (exact) OR natural-language query to resolve.",
    )
    parser.add_argument(
        "--path-params",
        dest="path_params",
        default=None,
        help="JSON object or @file.json for path parameters.",
    )
    parser.add_argument(
        "--query-params",
        dest="query_params",
        default=None,
        help="JSON object or @file.json for query parameters.",
    )
    parser.add_argument(
        "--body",
        dest="body",
        default=None,
        help="JSON object or @file.json for request body.",
    )
    parser.add_argument(
        "--spec",
        dest="spec",
        default=None,
        help=(
            "Raw RequestSpec JSON: pass a path, or '-' to read from stdin. "
            "Bypasses --op / flag-based construction."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirmed-write", action="store_true")
    parser.add_argument(
        "--auto-paginate",
        action="store_true",
        help="For GET list endpoints: aggregate pages into a single list.",
    )
    return parser.parse_args(argv)


def _load_spec_from_source(
    source: str, *, stdin_text: str | None
) -> RequestSpec:
    if source == "-":
        text = stdin_text if stdin_text is not None else sys.stdin.read()
    else:
        text = Path(source).expanduser().read_text()
    return RequestSpec.model_validate_json(text)


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _resolve_via_rag(
    op_arg: str,
    env_tag: str,
    env_file: Path | None,
) -> tuple[dict[str, Any], Any, Any]:
    """Open client + RAG, resolve op, and return (op_dict, config, session).

    NOTE: clients are closed before return; the caller only needs the dict.
    The NextseekClient for the actual HTTP call is re-opened later.
    """
    config = load_environment(env_path=env_file, use_dev=(env_tag == "dev"))
    cache_base = resolve_plugin_cache_base()
    with NextseekClient(config=config) as http_client:
        with SchemaRAGClient(
            http_client,
            env_tag=env_tag,
            base_url=config.base_url,
            cache_base_dir=cache_base,
        ) as rag:
            session = rag.current_session_state()
            if session is None:
                raise _SessionMissing()
            op_dict = resolve_operation(
                op_arg, rag, env_tag, session.session_id, cache_base=cache_base
            )
    return op_dict, config, session


class _SessionMissing(Exception):
    pass


def _auto_paginate_get(
    client: NextseekClient,
    spec: RequestSpec,
    resolved_path: str,
) -> list:
    """Drive pagination.paginate() against a NExtSEEK list endpoint."""
    base_params = dict(spec.query_params or {})

    def fetch_page(page_num: int) -> PageEnvelope:
        params = dict(base_params)
        params.setdefault("page[number]", page_num)
        if page_num > 1:
            params["page[number]"] = page_num
        resp = client.request("GET", resolved_path, params=params)
        if isinstance(resp, list):
            results = resp
        elif isinstance(resp, dict):
            results = resp.get("results")
        else:
            results = None
        if results is None:
            results = []
        return PageEnvelope(
            results=list(results),
            next=resp.get("next") if isinstance(resp, dict) else None,
            total=resp.get("count") if isinstance(resp, dict) else None,
        )

    return paginate(fetch_page)


def main(argv: list[str] | None = None, *, stdin_text: str | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # ----- Resolve RequestSpec -----
    op_dict: dict[str, Any] | None = None
    if args.spec:
        try:
            spec = _load_spec_from_source(args.spec, stdin_text=stdin_text)
        except (OSError, json.JSONDecodeError) as exc:
            return _fail(f"could not read --spec {args.spec!r}: {exc}", EXIT_FAIL)
        except Exception as exc:  # pydantic.ValidationError
            return _fail(f"invalid RequestSpec JSON: {exc}", EXIT_FAIL)
    else:
        if not args.op:
            return _fail("either --op or --spec is required", EXIT_FAIL)

        # Parse flag values first so a bad JSON literal fails before HTTP.
        try:
            path_params = _load_json_arg(args.path_params) or {}
            query_params = _load_json_arg(args.query_params) or {}
            body = _load_json_arg(args.body)
        except (OSError, json.JSONDecodeError) as exc:
            return _fail(f"could not parse flag JSON: {exc}", EXIT_FAIL)

        try:
            op_dict, _config, _session = _resolve_via_rag(
                args.op, args.env, args.env_file
            )
        except SystemExit:
            raise
        except EnvMissingError as exc:
            return _fail(f"missing credentials ({exc})", EXIT_CONFIG)
        except _SessionMissing:
            return _fail("no session — run nextseek-init", EXIT_CONFIG)
        except (NextseekAuthError, NextseekAPIError, NextseekTimeoutError,
                NextseekClientError) as exc:
            return _fail(f"schema_rag call failed: {exc}", EXIT_API)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"op resolution failed: {exc}", EXIT_FAIL)

        try:
            spec = build_spec(
                op_dict,
                path_params=path_params,
                query_params=query_params,
                body=body,
            )
        except Exception as exc:  # pydantic.ValidationError
            return _fail(f"RequestSpec construction failed: {exc}", EXIT_FAIL)

    # ----- Build a FullEndpoint for the validator -----
    if op_dict is None:
        # --spec path: synthesize a minimal FullEndpoint from the spec so the
        # validator's structural checks (method alignment, path template)
        # always trivially pass; this mode trusts the user-supplied spec.
        full_endpoint = FullEndpoint.model_validate(
            {
                "operationId": spec.operation_id,
                "method": spec.method,
                "path": spec.endpoint,
                "description": "",
                "tags": [],
                "parameters": [],
                "request_schema": {},
                "response_schema": {},
                "relevance_score": 1.0,
            }
        )
    else:
        full_endpoint = FullEndpoint.model_validate(op_dict)

    # ----- Static validation -----
    # DENYLIST_BLOCK is handled by the --confirmed-write gate below (parity
    # with execute_request.py). All OTHER errors short-circuit here.
    result = validate_request(spec=spec, endpoint=full_endpoint)
    non_denylist_errors = [e for e in result.errors if e.code != "DENYLIST_BLOCK"]
    if non_denylist_errors:
        payload = {
            "ok": False,
            "errors": [e.to_dict() for e in non_denylist_errors],
        }
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return EXIT_VALIDATION

    resolved_path = result.rendered_path or spec.endpoint

    # ----- Write safety gate -----
    method_upper = spec.method.upper()
    if method_upper != "GET" and not args.confirmed_write:
        print(
            f"ERROR: non-GET request (method={method_upper!r}) requires "
            f"--confirmed-write to execute.",
            file=sys.stderr,
        )
        return EXIT_CONFIRM_REQUIRED

    # ----- Dry-run short-circuit -----
    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "status": "dry-run OK", "resolved_path": resolved_path},
                indent=2,
            )
        )
        return EXIT_OK

    # ----- Execute -----
    try:
        config = load_environment(
            env_path=args.env_file, use_dev=(args.env == "dev")
        )
    except EnvMissingError as exc:
        return _fail(f"missing credentials ({exc})", EXIT_CONFIG)

    try:
        with NextseekClient(config=config) as client:
            if args.auto_paginate and method_upper == "GET":
                data: Any = _auto_paginate_get(client, spec, resolved_path)
            else:
                if args.auto_paginate and method_upper != "GET":
                    print(
                        "WARN: --auto-paginate ignored for non-GET methods",
                        file=sys.stderr,
                    )
                data = client.request(
                    method_upper,
                    resolved_path,
                    params=spec.query_params or None,
                    json=spec.request_body if isinstance(spec.request_body, dict) else None,
                )
    except NextseekAuthError as exc:
        return _fail(str(exc), EXIT_API)
    except NextseekTimeoutError as exc:
        return _fail(str(exc), EXIT_API)
    except NextseekAPIError as exc:
        return _fail(str(exc), EXIT_API)
    except NextseekClientError as exc:
        return _fail(str(exc), EXIT_API)

    print(json.dumps(data, indent=2, default=str))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
