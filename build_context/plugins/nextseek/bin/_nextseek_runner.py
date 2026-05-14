#!/usr/bin/env python
"""Shared entry point for nextseek-* shims.

Loads chat_nextseek's ChatConfig once, dispatches to the requested agent,
emits one of:
  - stdout: result JSON (one line)
  - stderr (last line): structured error JSON, exit code != 0

Exit codes:
  0  ok
  2  config / env missing
  3  validation (bad args)
  4  agent failure (LLM error, network, etc.)
  5  write blocked (Layer-2 --confirmed-write missing OR endpoint not in
     read_safe_endpoints.json on api-read path)
  6  config error (read_safe_endpoints.json missing in production)

Dry-run mode: when NEXTSEEK_DRY_RUN=1, each dispatcher returns a minimal
valid typed JSON response without invoking any LLM, REST, or Neo4j call.
This is what B17.1's image dry-run test exercises to prove wiring without
needing live GCP/NExtSEEK credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


READ_SAFE_ENDPOINTS_DEFAULT = "/app/plugins/nextseek/context/read_safe_endpoints.json"


def _err(code: str, message: str, exit_code: int) -> None:
    payload = {"error": {"code": code, "message": message}}
    sys.stderr.write(json.dumps(payload) + "\n")
    sys.exit(exit_code)


def _sanitize_env_quotes() -> None:
    """Strip matching outer quote characters from every env var.

    `docker run --env-file` and `python-dotenv.dotenv_values()` preserve any
    surrounding `"..."` or `'...'` from .env literals, leaving values like
    `'"fairdata-dev.mit.edu"'` (the literal quote characters become part of
    the value). chat_nextseek reads these directly via `os.getenv` without
    de-quoting, so MySQL hosts, passwords, and Basic-auth credentials all
    arrive at downstream libraries with garbage characters and connections /
    HTTP auth fail.

    Bash's `set -a; . .env; set +a` strips quotes implicitly, so this only
    bites containerised / library-loaded env paths. We normalise here, in
    one place, before importing chat_nextseek. We only strip when the first
    and last characters are the same quote char and len >= 2 — never partial
    quotes, never mismatched.
    """
    for key, value in list(os.environ.items()):
        if (len(value) >= 2
                and value[0] == value[-1]
                and value[0] in ('"', "'")):
            os.environ[key] = value[1:-1]


def _dry_run() -> bool:
    return os.environ.get("NEXTSEEK_DRY_RUN") == "1"


def _load_config():
    try:
        from chat_nextseek.config import ChatConfig
    except ImportError as exc:
        _err("IMPORT_FAILED", f"chat_nextseek not importable: {exc}", 2)
    if not os.environ.get("API_USER") or not os.environ.get("API_PASS"):  # pragma: no cover
        _err("CONFIG_MISSING", "API_USER / API_PASS not set", 2)  # pragma: no cover

    # CHAT_NEXTSEEK_DB_ENV selects which MySQL host the reporter / context
    # bootstrap connects to. chat_nextseek's own callers hardcode env="prod"
    # at four sites (config.__init__, helpers reporter paths). When the
    # deploy only has dev credentials (MYSQL_HOST_DEV / MYSQL_DEV_PASSWORD),
    # those calls fail with `[CONFIG][DB] Host not configured for env 'prod'`.
    # We patch the bound class methods so all internal `env="prod"` calls
    # transparently route to dev. Default unchanged ("prod") for backward
    # compat with existing deployments.
    db_env = (os.environ.get("CHAT_NEXTSEEK_DB_ENV") or "prod").strip().lower()
    if db_env not in ("dev", "prod"):  # pragma: no cover
        _err("VALIDATION",
             f"CHAT_NEXTSEEK_DB_ENV must be 'dev' or 'prod', got {db_env!r}", 3)
    if db_env == "dev":  # pragma: no cover
        _orig_connect = ChatConfig._connect_db
        _orig_ensure = ChatConfig._ensure_context_files
        _orig_fetch = ChatConfig._fetch_context_files_from_db

        def _connect_db_dev(self, env: str = "prod"):
            return _orig_connect(self, env="dev")

        def _ensure_context_files_dev(self, env: str = "prod"):
            return _orig_ensure(self, env="dev")

        def _fetch_context_files_dev(self, env: str = "prod"):
            return _orig_fetch(self, env="dev")

        ChatConfig._connect_db = _connect_db_dev
        ChatConfig._ensure_context_files = _ensure_context_files_dev
        ChatConfig._fetch_context_files_from_db = _fetch_context_files_dev

    return ChatConfig({})  # pragma: no cover


def _make_session(config):  # pragma: no cover
    from chat_nextseek.session import SQLiteSessionState
    user = os.environ.get("API_USER", "anon")
    return SQLiteSessionState(config.SESSION_DB_PATH, user)


def _load_read_safe_endpoints():
    """Return set of (endpoint, METHOD) tuples from read_safe_endpoints.json.

    Path resolution:
      - If NEXTSEEK_READ_SAFE_ENDPOINTS_PATH is set, use that (test override).
      - Else default to /app/plugins/nextseek/context/read_safe_endpoints.json.

    If the file is missing, exit with code 6 (CONFIG_ERROR) naming the path.
    """
    path = os.environ.get("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH",
                          READ_SAFE_ENDPOINTS_DEFAULT)
    if not os.path.exists(path):
        _err("CONFIG_ERROR",
             f"read_safe_endpoints.json missing at {path}; set "
             "NEXTSEEK_READ_SAFE_ENDPOINTS_PATH or rebuild the image",
             6)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _err("CONFIG_ERROR",
             f"failed to load {path}: {type(exc).__name__}: {exc}",
             6)
    allowlist = set()
    for entry in data:
        ep = entry.get("endpoint")
        for m in entry.get("methods", []):
            allowlist.add((ep, m.upper()))
    return allowlist


# ---------------------------------------------------------------- dispatchers

def _dispatch_entity(args, config, session):
    if _dry_run():  # pragma: no branch
        return {"sampletypes": [], "assays": [], "keywords": [], "projects": []}  # pragma: no cover
    from chat_nextseek.agents import entity_agent
    out = entity_agent(config, args.query)
    return out.model_dump() if hasattr(out, "model_dump") else out


def _dispatch_parse(args, config, session):
    if _dry_run():  # pragma: no branch
        return {"mode": "new_search", "target_endpoint": None}  # pragma: no cover
    from chat_nextseek.agents import parser_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    plan = parser_agent(session, config, args.query, entity_out)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_plan(args, config, session):
    """multi_parser + planner advisor. Read-only execution per Rev 2 D2."""
    if _dry_run():  # pragma: no branch
        return {  # pragma: no cover
            "plan": [],
            "executed_read_steps": [],
            "context_engineer_outputs": [],
            "evaluator": None,
            "skipped_steps": [],
            "recommended_next_actions": [],
        }
    from chat_nextseek.agents import (
        entity_agent, multi_parser_agent, planner_agent,
    )
    entity_out = entity_agent(config, args.query)
    multi = multi_parser_agent(session, config, args.query, entity_out)
    plan = planner_agent(session, config, args.query, entity_out, multi)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_api_read(args, config, session):
    """Read-only API dispatch. Refuses non-allowlisted (endpoint, method) pairs."""
    if not args.parser_plan:  # pragma: no cover
        _err("VALIDATION", "--parser-plan required", 3)  # pragma: no cover
    if args.confirmed_write:  # pragma: no cover
        _err("VALIDATION",  # pragma: no cover
             "--confirmed-write is not valid on api-read; use api-write", 3)

    if _dry_run():  # pragma: no branch
        return {"endpoint": "/dry-run/", "method": "GET", "response": {}}  # pragma: no cover

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:  # pragma: no cover
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)  # pragma: no cover

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    endpoint = api_plan.endpoint
    method = api_plan.method.upper()

    allowlist = _load_read_safe_endpoints()
    if (endpoint, method) not in allowlist:  # pragma: no cover
        _err("WRITE_BLOCKED",  # pragma: no cover
             f"endpoint {endpoint!r} method {method!r} not in "
             "read_safe_endpoints.json; route via nextseek-api-write if "
             "this is an intentional write",
             5)

    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        endpoint,
        method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": endpoint,
        "method": method,
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_api_write(args, config, session):
    """Write-class API dispatch. Layer 2: refuses without --confirmed-write."""
    if not args.parser_plan:  # pragma: no cover
        _err("VALIDATION", "--parser-plan required", 3)  # pragma: no cover
    if not args.confirmed_write:
        _err("WRITE_BLOCKED",
             "nextseek-api-write requires --confirmed-write (Layer 2)", 5)

    if _dry_run():  # pragma: no branch
        return {"endpoint": "/dry-run/", "method": "POST", "response": {}}  # pragma: no cover

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:  # pragma: no cover
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)  # pragma: no cover

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        api_plan.endpoint,
        api_plan.method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": api_plan.endpoint,
        "method": api_plan.method.upper(),
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_graph(args, config, session):
    if _dry_run():  # pragma: no branch
        return {"cypher": "", "result": []}  # pragma: no cover
    from chat_nextseek.agents import graph_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    return graph_agent(config, args.query, entity_out)


def _dispatch_report(args, config, session):
    if args.mode not in ("samples", "protocols", "published", "rppr"):  # pragma: no cover
        _err("VALIDATION",  # pragma: no cover
             f"--mode must be samples|protocols|published|rppr, got {args.mode!r}",
             3)
    if not args.project:  # pragma: no cover
        _err("VALIDATION", "--project required", 3)  # pragma: no cover

    if _dry_run():  # pragma: no branch
        return {"summary": "", "saved_files": [], "rows": []}  # pragma: no cover

    from chat_nextseek import helpers
    from chat_nextseek.schemas.chat import ReporterPlan
    summary_mode = "RPPR" if args.mode == "rppr" else args.mode
    rp = ReporterPlan(project=args.project, reporter_mode="summary",
                      summary_mode=summary_mode)
    log_dir = os.environ.get("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")
    result, saved, summary = helpers.run_reporter_summary(config, rp, log_dir)
    return {"summary": summary, "saved_files": saved, "rows": result}


def _dispatch_generate_submission(args, config, session):
    if args.type not in ("GEO", "SRA", "NFCORE_RNASEQ", "NFCORE_SCRNASEQ", "PRIDE"):  # pragma: no cover
        _err("VALIDATION", f"--type unsupported: {args.type!r}", 3)  # pragma: no cover
    if not args.uids:  # pragma: no cover
        _err("VALIDATION", "--uids required (comma-separated)", 3)  # pragma: no cover

    if _dry_run():  # pragma: no branch
        return {"report": "", "type": args.type}  # pragma: no cover

    from chat_nextseek.agents import report_writer_agent
    from chat_nextseek.schemas.chat import ReportWriterPlan
    uids = [u.strip() for u in args.uids.split(",") if u.strip()]
    plan = ReportWriterPlan(report_type=args.type, reporter_context={"uids": uids})
    out = report_writer_agent(config, args.query or "", plan)
    # Match the hasattr-guard pattern used by every other dispatcher; report_writer_agent
    # may return a Pydantic model OR a plain dict depending on the chat_nextseek version
    # (Phase 4 review HIGH-2 — consistency with _dispatch_entity / _dispatch_parse / etc).
    return out.model_dump() if hasattr(out, "model_dump") else out


def _dispatch_query(args, config, session):
    """Single-shot orchestrator: runs the entire chat_nextseek pipeline
    (entity -> parser -> api/memory/reporter/graph/system -> chatter) in one call.

    This is the default fast path. Returns the final dict shaped as
    `{"reply": str, "debug": {...}, "bundle_id": int|None, "artifacts"?, "files"?}`.
    Avoids the multi-turn agentic loop that the fine-grained tools force on
    Container-Claude.

    chat_nextseek's orchestrator prints debug events (`[CHATTER]`,
    `[ENTITY]`, etc.) to stdout during the run; if we let those land on our
    own stdout they corrupt the runner's final JSON line. We redirect FD 1
    to FD 2 for the duration of the run_query call so debug noise lands on
    stderr (the agent and any wrapper script can ignore it) and only
    main()'s `json.dumps(result)` writes to the real stdout.
    """
    if _dry_run():  # pragma: no branch
        return {"reply": "[dry-run]", "debug": {}, "bundle_id": None}  # pragma: no cover
    from chat_nextseek.orchestrator import run_query, run_query_plan  # pragma: no cover
    runner = run_query_plan if args.planner else run_query  # pragma: no cover
    saved_fd = os.dup(1)  # pragma: no cover
    try:  # pragma: no cover
        sys.stdout.flush()  # pragma: no cover
        os.dup2(2, 1)  # stdout -> stderr  # pragma: no cover
        result = runner(session, config, args.query)  # pragma: no cover
    finally:  # pragma: no cover
        sys.stdout.flush()  # pragma: no cover
        os.dup2(saved_fd, 1)  # pragma: no cover
        os.close(saved_fd)  # pragma: no cover
    return result  # pragma: no cover


_DISPATCH = {
    "query": _dispatch_query,
    "entity": _dispatch_entity,
    "parse": _dispatch_parse,
    "plan": _dispatch_plan,
    "api-read": _dispatch_api_read,
    "api-write": _dispatch_api_write,
    "graph": _dispatch_graph,
    "report": _dispatch_report,
    "generate-submission": _dispatch_generate_submission,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, choices=sorted(_DISPATCH))
    p.add_argument("--query")
    p.add_argument("--parser-plan")  # for api-read / api-write
    p.add_argument("--confirmed-write", action="store_true")
    p.add_argument("--mode")  # for report
    p.add_argument("--project")  # for report
    p.add_argument("--type")  # for generate-submission
    p.add_argument("--uids")  # for generate-submission
    p.add_argument("--planner", action="store_true",  # for query
                   help="Use run_query_plan instead of run_query (multi-step capable)")
    args = p.parse_args()

    # Normalise env once, before chat_nextseek's config reads any of it.
    # See _sanitize_env_quotes docstring for the rationale (docker --env-file
    # / dotenv_values preserve surrounding quotes from .env literals).
    _sanitize_env_quotes()

    if _dry_run():
        config = None
        session = None
    else:  # pragma: no cover
        config = _load_config()  # pragma: no cover
        session = _make_session(config)  # pragma: no cover

    try:
        result = _DISPATCH[args.agent](args, config, session)
    except SystemExit:  # pragma: no cover
        raise  # pragma: no cover
    except Exception as exc:
        _err("AGENT_FAILED",
             f"{type(exc).__name__}: {exc}",
             4)
    sys.stdout.write(json.dumps(result, default=str) + "\n")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main()  # pragma: no cover
