"""The 7 granular sidecar ops, each calling chat_nextseek portable.py (recon:chatNs §1).

Call shapes mirror the pre-sidecar runner dispatchers (recon:runner §1j) so behavior
is preserved. portable.py imports are lazy (chat_nextseek is image-only).
write_gate(op, api_plan_endpoint, api_plan_method, confirmed_write) -> None|raises.
stage(op, result) -> result' (T7 rewrites artifact paths to staged paths; default identity).
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from sidecar.app.contract import SIDECAR_OPS


class OpValidationError(ValueError):
    """→ VALIDATION / exit 3."""


class WriteBlockedError(RuntimeError):
    """→ WRITE_BLOCKED / exit 5."""


def ALLOW_ALL(*a, **k) -> None:  # T4 default; T5 replaces with the real gate
    return None


def NO_STAGE(op: str, result: dict) -> dict:  # T4 default; T7 replaces
    return result


def _dump(obj: Any) -> Any:
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def _load_parser_plan(args: dict) -> Any:
    """Parse args["parser_plan"] as JSON; malformed input → OpValidationError so the
    server maps it to VALIDATION/exit 3 (pre-sidecar runner parity, recon:runner §1j:
    `_err("VALIDATION", "--parser-plan is not valid JSON: ...", 3)`), not AGENT_FAILED."""
    try:
        return json.loads(args["parser_plan"])
    except ValueError as exc:  # json.JSONDecodeError is a ValueError subclass
        raise OpValidationError(f"parser_plan is not valid JSON: {exc}") from exc


def run_op(op: str, args: dict, *, config: Any, session: Any,
           write_gate: Callable, stage: Callable) -> dict:
    if op not in SIDECAR_OPS:
        raise OpValidationError(f"not a sidecar op: {op!r}")
    handler = _HANDLERS[op]
    return handler(args, config, session, write_gate, stage)


def _entity(args, config, session, write_gate, stage):
    from chat_nextseek.portable import entity_agent
    return _dump(entity_agent(config, args["query"]))


def _parse(args, config, session, write_gate, stage):
    from chat_nextseek.portable import entity_agent, parser_agent
    entity_out = entity_agent(config, args["query"])
    return _dump(parser_agent(session, config, args["query"], entity_out))


def _graph(args, config, session, write_gate, stage):
    from chat_nextseek.portable import entity_agent, graph_agent
    entity_out = entity_agent(config, args["query"])
    return _dump(graph_agent(config, args["query"], entity_out))


def _api_read(args, config, session, write_gate, stage):
    from chat_nextseek import helpers
    from chat_nextseek.portable import api_agent_build_request
    plan = api_agent_build_request(config, _load_parser_plan(args))
    endpoint, method = plan.endpoint, plan.method.upper()
    write_gate("api-read", endpoint, method, False)  # raises WriteBlocked if not read-safe
    result = helpers.tool_nextseek_api_request(config, endpoint, method,
                                               requestBody=plan.requestBody,
                                               queryParameters=plan.queryParameters)
    return {"endpoint": endpoint, "method": method, "api_plan": _dump(plan), "response": result}


def _api_write(args, config, session, write_gate, stage):
    from chat_nextseek import helpers
    from chat_nextseek.portable import api_agent_build_request
    confirmed = args.get("confirmed_write", False)
    write_gate("api-write", None, None, confirmed)  # raises WriteBlocked if confirmed is not True
    plan = api_agent_build_request(config, _load_parser_plan(args))
    result = helpers.tool_nextseek_api_request(config, plan.endpoint, plan.method,
                                               requestBody=plan.requestBody,
                                               queryParameters=plan.queryParameters)
    return {"endpoint": plan.endpoint, "method": plan.method.upper(),
            "api_plan": _dump(plan), "response": result}


def _report(args, config, session, write_gate, stage):
    from chat_nextseek import helpers
    from chat_nextseek.schemas.chat import ReporterPlan
    mode = args["mode"]
    summary_mode = "RPPR" if mode == "rppr" else mode
    rp = ReporterPlan(project=args["project"], reporter_mode="summary", summary_mode=summary_mode)
    log_dir = os.environ.get("NEXTSEEK_OUTPUTS_DIR", "/staging/_report_logs")
    result, saved, summary = helpers.run_reporter_summary(config, rp, log_dir)
    return stage("report", {"summary": summary, "saved_files": saved, "rows": result})


def _generate_submission(args, config, session, write_gate, stage):
    from chat_nextseek.portable import report_writer_agent
    from chat_nextseek.schemas.chat import ReportWriterPlan
    uids = [u.strip() for u in args["uids"].split(",") if u.strip()]
    plan = ReportWriterPlan(report_type=args["type"], reporter_context={"uids": uids})
    out = report_writer_agent(config, args.get("query") or "", plan)
    return stage("generate-submission", _dump(out))


_HANDLERS: dict[str, Callable] = {
    "entity": _entity, "parse": _parse, "graph": _graph,
    "api-read": _api_read, "api-write": _api_write,
    "report": _report, "generate-submission": _generate_submission,
}
