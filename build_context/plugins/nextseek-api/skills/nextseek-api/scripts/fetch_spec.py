"""Fetch the full spec for a single NExtSEEK endpoint via SchemaRAG.

Lookup modes:
  --operation-id ID    Exact-match lookup against operationId.
  --query STR          Semantic search; top relevance_score wins.

Cache behavior (DD-7, task-06b):
  Per-operation lazy cache at
  ``~/.cache/nextseek-api/v2/{env}/endpoints_full/{op_id}.json``. On every
  ``--operation-id`` fetch:
    1. If the cache file exists AND its ``session_id`` matches the current
       session, stream the cached ``spec`` back verbatim.
    2. Otherwise, hit SchemaRAG, write-through
       ``{"session_id": ..., "spec": {...}}``, return.
  ``nextseek-init --clear-cache`` wipes the whole env dir (including
  ``endpoints_full/``), so a session reingest always invalidates per-op caches.

Output shape (stdout, JSON):
  Default::
      {"spec": {...full endpoint dict...},
       "request_spec_template": {...prefilled RequestSpec skeleton...}}
  ``--print-example``::
      {...RequestSpec...}          # ready to pipe to ``nextseek-call --spec -``

Optional query parameters are reported to stderr (free-form, not JSON) so
agents that parse only stdout aren't confused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# CL-1: All lib imports via `from lib.X import ...`. The task-01 conftest.py
# puts `scripts/` on sys.path so `lib.*` resolves at test time and runtime.
from lib.cache_paths import (
    resolve_endpoint_full_path,
    resolve_endpoints_full_dir,
    resolve_plugin_cache_base,
)
from lib.cli_common import add_env_file_arg
from lib.env_loader import EnvMissingError, load_environment
from lib.models import FullEndpoint, SchemaRAGResponse
from lib.nextseek_client import NextseekClient, NextseekConfig
from lib.schema_rag_client import SchemaRAGClient

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_API = 2
EXIT_CONFIG = 3

# Placeholders used by the request_spec_template skeleton. Scalar types map
# to sentinel values; strings use "<string>" so agents can pattern-match.
_TYPE_PLACEHOLDERS: dict[str, Any] = {
    "string": "<string>",
    "integer": 0,
    "number": 0.0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _normalize_parameters(
    parameters: list[dict[str, Any]] | dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize both OpenAPI-native list[dict] and legacy dict[str, dict]
    parameter shapes into a single list[dict] form. Per CL-6."""
    if not parameters:
        return []
    if isinstance(parameters, dict):
        return [{"name": name, **(p or {})} for name, p in parameters.items()]
    return list(parameters)


def _skeleton_from_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Produce a shallow skeleton dict for a JSON Schema object type.

    Only the top-level required properties are emitted; values are the type
    placeholders from ``_TYPE_PLACEHOLDERS``. Non-object schemas return {}.
    """
    if not schema or schema.get("type") != "object":
        return {}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    for name, prop in (schema.get("properties") or {}).items():
        if name in required:
            prop_type = (prop or {}).get("type")
            out[name] = _TYPE_PLACEHOLDERS.get(prop_type, "<value>")
    return out


def build_request_spec_template(full: dict[str, Any]) -> dict[str, Any]:
    """Build a pre-filled RequestSpec skeleton from a FullEndpoint dict.

    DD-6: path params and required query params get ``"<value>"``
    placeholders. Optional query params are NOT included — agents can read
    the stderr note (or the full ``spec.parameters`` field) to discover them.
    POST endpoints additionally get a shallow ``request_body`` skeleton
    derived from ``request_schema``.
    """
    method = str(full.get("method", "GET")).upper()
    endpoint = full.get("endpoint") or ""
    path_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    for p in _normalize_parameters(full.get("parameters")):
        name = p.get("name")
        loc = p.get("in")
        required = bool(p.get("required", False))
        if not name:
            continue
        if loc == "path":
            path_params[name] = "<value>"
        elif loc == "query" and required:
            query_params[name] = "<value>"
    request_body: dict[str, Any] | None = None
    if method == "POST":
        request_body = _skeleton_from_schema(full.get("request_schema"))
    return {
        "operation_id": full.get("operation_id"),
        "method": method,
        "endpoint": endpoint,
        "path_params": path_params,
        "query_params": query_params,
        "headers": {},
        "request_body": request_body,
    }


def _lazy_fetch_full(
    op_id: str,
    client: SchemaRAGClient,
    env_tag: str,
    session_id: str,
    *,
    cache_base: Path | None = None,
) -> dict[str, Any]:
    """Lazy per-operation full-spec cache (DD-7).

    Returns the spec dict. Writes through on miss using a session-scoped
    wrapper ``{"session_id": ..., "spec": {...}}``. Cache entries written
    under a different session_id are treated as stale and rewritten.

    Raises LookupError if SchemaRAG cannot resolve the operation_id.
    """
    cache_file = resolve_endpoint_full_path(
        env_tag, op_id, cache_base=cache_base
    )
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            cached = None
        if (
            isinstance(cached, dict)
            and cached.get("session_id") == session_id
            and isinstance(cached.get("spec"), dict)
        ):
            return cached["spec"]

    endpoint = client.retrieve_full(op_id)
    spec_dict = endpoint.model_dump(by_alias=False)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {"session_id": session_id, "spec": spec_dict},
            indent=2,
            default=str,
        )
    )
    tmp.replace(cache_file)
    return spec_dict


def _select_endpoint(
    results: list[FullEndpoint],
    operation_id: str | None,
) -> FullEndpoint | None:
    """Pick a FullEndpoint from a retrieve response (legacy path)."""
    if not results:
        return None
    if operation_id:
        for ep in results:
            if ep.operation_id == operation_id:
                return ep
        return None
    return max(results, key=lambda ep: float(ep.relevance_score or 0.0))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fetch_spec.py",
        description=(
            "Fetch a NExtSEEK endpoint spec and emit a request_spec_template "
            "(pipeable to nextseek-exec --file -)."
        ),
        epilog=(
            "Examples:\n"
            "  fetch_spec.py --env dev --operation-id ListAssays\n"
            "    -> {\"spec\": {...}, \"request_spec_template\": {\"operation_id\": \"ListAssays\", ...}}\n\n"
            "  fetch_spec.py --env dev --operation-id ListAssays --print-example\n"
            "    -> {\"operation_id\": \"ListAssays\", \"method\": \"GET\", ...}\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env", choices=["dev", "prod"], required=True)
    add_env_file_arg(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--operation-id", dest="operation_id")
    group.add_argument("--query", dest="query")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-fetch even if cached file exists.",
    )
    parser.add_argument(
        "--print-example",
        action="store_true",
        help=(
            "Print only the request_spec_template JSON (ready to pipe to "
            "nextseek-exec --file -)."
        ),
    )
    return parser.parse_args(argv)


def _emit(
    spec_dict: dict[str, Any],
    *,
    print_example: bool,
) -> None:
    """Emit the stdout JSON and any optional-param stderr note."""
    template = build_request_spec_template(spec_dict)

    if print_example:
        print(json.dumps(template, indent=2, default=str))
    else:
        print(
            json.dumps(
                {"spec": spec_dict, "request_spec_template": template},
                indent=2,
                default=str,
            )
        )
        optional = [
            p.get("name")
            for p in _normalize_parameters(spec_dict.get("parameters"))
            if p.get("in") == "query" and not p.get("required") and p.get("name")
        ]
        if optional:
            print(
                f"[nextseek-spec] optional query params: {', '.join(optional)}",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # CL-7: ensure the per-env endpoints_full/ dir exists before any I/O.
    resolve_endpoints_full_dir(args.env).mkdir(parents=True, exist_ok=True)

    # CL-12: load_environment returns a NextseekConfig directly.
    try:
        config: NextseekConfig = load_environment(
            env_path=args.env_file,
            use_dev=(args.env == "dev"),
        )
    except EnvMissingError as exc:
        print(f"ERROR: missing credentials ({exc})", file=sys.stderr)
        return EXIT_CONFIG

    cache_base = resolve_plugin_cache_base()

    # CL-3: SchemaRAGClient is a context manager; kwargs are http_client
    # (positional), env_tag, base_url, cache_base_dir. task-06b routes every
    # --operation-id fetch through _lazy_fetch_full; --query bypasses the
    # cache (no known op_id) and falls back to the legacy retrieve path.
    try:
        with NextseekClient(config=config) as http_client:  # pragma: no cover
            with SchemaRAGClient(
                http_client,
                env_tag=args.env,
                base_url=config.base_url,
                cache_base_dir=cache_base,
            ) as rag_client:
                session = rag_client.current_session_state()
                if session is None:
                    print(
                        "[nextseek-spec] no session -- run nextseek-init",
                        file=sys.stderr,
                    )
                    return EXIT_CONFIG

                if args.operation_id and not args.no_cache:
                    spec_dict = _lazy_fetch_full(
                        args.operation_id,
                        rag_client,
                        args.env,
                        session.session_id,
                        cache_base=cache_base,
                    )
                    _emit(spec_dict, print_example=args.print_example)
                    return EXIT_OK

                # Legacy path: --query OR --no-cache.
                query = args.query or (args.operation_id or "")
                response: SchemaRAGResponse = rag_client.retrieve_with_auto_ingest(
                    query=query,
                    mode="full",
                    top_k=5,
                    min_score=0.0,
                )
                session_id = session.session_id
    except LookupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: API call failed: {exc}", file=sys.stderr)
        return EXIT_API

    # Legacy path post-processing.
    results: list[FullEndpoint] = list(response.endpoints)
    selected = _select_endpoint(results, args.operation_id)
    if selected is None:
        msg = (
            f"No match for operation_id={args.operation_id!r}"
            if args.operation_id
            else "No results returned from SchemaRAG"
        )
        print(f"ERROR: {msg}", file=sys.stderr)
        return EXIT_FAIL

    spec_dict = selected.model_dump(by_alias=False)
    op_id = spec_dict.get("operation_id") or "unknown"

    cache_file = resolve_endpoint_full_path(args.env, op_id, cache_base=cache_base)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {"session_id": session_id, "spec": spec_dict},
            indent=2,
            default=str,
        )
    )
    tmp.replace(cache_file)

    _emit(spec_dict, print_example=args.print_example)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
