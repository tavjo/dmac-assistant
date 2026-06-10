"""Sidecar WS server: accept → validate (T2) → build per-user config/session →
dispatch (T4 ops) → typed response. Per-call NS login => runs as that user (U-2)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets
from pydantic import ValidationError

from sidecar.app import ops
from sidecar.app.config import SidecarConfig
from sidecar.app.contract import NsLogin, SidecarError, SidecarRequest, SidecarResponse

_CFG: SidecarConfig | None = None


def _err_response(request_id: str, code: str, message: str, retryable: bool = False) -> str:
    return SidecarResponse(request_id=request_id, status="error", result=None,
                           error=SidecarError(code=code, message=message, retryable=retryable)
                           ).model_dump_json()


def _build_user_config(login: NsLogin) -> Any:
    """Build a chat_nextseek ChatConfig bound to the per-call user login (U-2).

    Shared backend creds (GCP/Neo4j/MySQL) come from the sidecar process env;
    the user's NS REST login is injected per call so portable ops act as that user.
    """
    import os
    # CREDENTIAL-SAFETY INVARIANT (vet-verified): this function MUST stay synchronous on
    # the event-loop thread. The env mutation + eager ChatConfig({}) capture below, with
    # NO await between them, is what prevents cross-user credential bleed. Do NOT wrap
    # this function or the setup block in asyncio.to_thread / an executor to "fix" the
    # loop-blocking cost — that reintroduces the race.
    os.environ["API_USER"] = login.api_user   # process-local; chat_nextseek reads these
    os.environ["API_PASS"] = login.api_pass    # (recon:chatNs §4)
    from chat_nextseek.config import ChatConfig
    return ChatConfig({})


def _build_user_session(login: NsLogin, config: Any) -> Any:
    from sidecar.app.sessions import make_session  # T6
    return make_session(login, config, _CFG)


def _build_write_gate():
    from sidecar.app.write_gate import build_gate  # T5
    return build_gate(_CFG)


def _build_stage(request_id: str, login: NsLogin):
    from sidecar.app.staging import make_stage  # T7
    return make_stage(_CFG, login, request_id)


async def handle_message(raw: str) -> str:
    request_id = "00000000-0000-4000-8000-000000000000"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _err_response(request_id, "TRANSPORT_ERROR", "malformed JSON frame")
    # Adopt the client's request_id only when it is a str: SidecarResponse(request_id=int)
    # would itself raise ValidationError inside the except handler below, escaping
    # handle_message and killing the connection (1011) instead of replying VALIDATION.
    if isinstance(data, dict) and isinstance(data.get("request_id"), str):
        request_id = data["request_id"]
    try:
        req = SidecarRequest(**data)
    except ValidationError as exc:
        return _err_response(request_id, "VALIDATION", f"bad request: {exc.error_count()} errors")
    except TypeError:  # e.g. top-level JSON array: SidecarRequest(**list) is a TypeError
        return _err_response(request_id, "VALIDATION", "bad request: envelope must be a JSON object")

    # §12: reject malformed per-op args BEFORE touching shared resources (vet finding 15).
    try:
        from sidecar.app.contract import validate_op_args
        validate_op_args(req.op, req.args)
    except (ValidationError, ValueError) as exc:
        return _err_response(req.request_id, "VALIDATION", f"bad args for {req.op}: {exc}")

    try:
        config = _build_user_config(req.ns_login)
        session = _build_user_session(req.ns_login, config)
        gate = _build_write_gate()
        stage = _build_stage(req.request_id, req.ns_login)
    except Exception as exc:  # noqa: BLE001
        return _err_response(req.request_id, "CONFIG_ERROR", f"setup failed: {type(exc).__name__}")

    try:
        result = await asyncio.to_thread(
            ops.run_op, req.op, req.args, config=config, session=session,
            write_gate=gate, stage=stage,
        )
    except ops.OpValidationError as exc:
        return _err_response(req.request_id, "VALIDATION", str(exc))
    except ops.WriteBlockedError as exc:
        return _err_response(req.request_id, "WRITE_BLOCKED", str(exc))
    except Exception as exc:  # noqa: BLE001 — downstream LLM/API/Neo4j failure
        return _err_response(req.request_id, "AGENT_FAILED", f"{type(exc).__name__}")

    return SidecarResponse(request_id=req.request_id, status="ok", result=result,
                           error=None).model_dump_json()


async def _serve_conn(ws) -> None:  # pragma: no cover — requires a real socket (pytest-socket disabled)
    async for raw in ws:
        await ws.send(await handle_message(raw))


async def serve() -> None:  # pragma: no cover — requires a real socket (pytest-socket disabled)
    global _CFG
    _CFG = SidecarConfig.from_env()
    async with websockets.serve(_serve_conn, "0.0.0.0", _CFG.ws_port, max_size=16 * 1024 * 1024):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(serve())
