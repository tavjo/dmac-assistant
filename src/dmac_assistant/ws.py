"""T06: WebSocket bridge endpoint at ``/ws/chat``.

Authenticates the upgrade against ``TokenStore``, resolves (or skips)
auto-resume against the mounted ``.claude/`` tree, launches one Claude
container via T05's docker-py wrapper, and relays Claude's stream-json
output back to the chat UI.

Invariants (spec §3):
  * Missing / bad Authorization -> close(4401) before ``accept``.
  * Malformed first frame -> error frame + close(4400).
  * Container-start failure -> error frame + close(1011) + cleanup.
  * Frame ordering on resume mismatch: ``error(reason="resume_failed", ...)``
    FIRST, then ``session_started`` with the actual session id (DD-14).
  * ``session_started`` precedes any assistant / tool_use frame.
  * On clean EOF without an explicit Claude ``result`` event, a final
    ``session_ended`` frame is still emitted before close.
  * Every exit path uses ``try/finally`` (no ``asyncio.shield``) to close
    the attach socket and stop the container if they exist.
  * No logging of ``AuthenticatedIdentity``, ``bridge_env``, raw headers,
    NExtSEEK passwords, or ``AWS_BEARER_TOKEN_BEDROCK`` (R-03).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from dmac_assistant.auth import AuthenticationError, TokenStore, get_token_store
from dmac_assistant.config import load_config
from dmac_assistant.containers import (
    async_attach,
    async_start_container,
    async_stop_and_remove,
)
from dmac_assistant.sessions import most_recent_session
from dmac_assistant.streamjson import StreamEvent, StreamJsonParser

router = APIRouter()
log = logging.getLogger(__name__)

DEFAULT_IMAGE = "dmac-assistant:poc"
CWD = "/home/user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_websocket_identity(
    websocket: WebSocket, token_store: TokenStore
):
    authorization = websocket.headers.get("authorization")
    if not authorization:
        raise AuthenticationError("missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("invalid authorization header")
    return token_store.verify(token)


def stream_event_to_ws_frames(
    event: StreamEvent, *, current_session_id: str | None
) -> list[dict[str, Any]]:
    """Translate one parser event into zero or more WS frames.

    ``system/init`` events are handled by the caller (needs mismatch logic).
    This function handles the content-only subset: assistant text blocks,
    tool_use blocks, result events, and parser errors.
    """
    if event.kind == "error":
        return [
            {
                "type": "error",
                "reason": "stream_json_error",
                "detail": event.error.reason if event.error else "",
            }
        ]

    payload = event.payload or {}
    etype = payload.get("type")
    if etype == "assistant":
        frames: list[dict[str, Any]] = []
        content = (payload.get("message") or {}).get("content") or []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                frames.append(
                    {"type": "assistant_message", "content": block["text"]}
                )
            elif btype == "tool_use":
                tool_input = block.get("input")
                frames.append(
                    {
                        "type": "tool_use",
                        "tool": block.get("name"),
                        "input": tool_input
                        if isinstance(tool_input, dict)
                        else {},
                        "id": block.get("id"),
                    }
                )
        return frames
    if etype == "result":
        return [
            {"type": "session_ended", "session_id": current_session_id}
        ]
    return []


async def _send_json_safe(websocket: WebSocket, frame: dict[str, Any]) -> bool:
    """Best-effort send. Returns False if the socket is already gone."""
    if websocket.client_state != WebSocketState.CONNECTED:
        return False  # pragma: no cover — defensive; send path always guards upstream
    try:
        await websocket.send_json(frame)
        return True
    except (WebSocketDisconnect, RuntimeError):  # pragma: no cover — race guard
        return False


async def _read_frame(attach_socket: Any) -> tuple[str, bytes] | None:
    """Run the blocking attach read in a worker thread."""
    return await asyncio.to_thread(attach_socket.read_frame)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/chat")
async def chat_ws(
    websocket: WebSocket,
    token_store: TokenStore = Depends(get_token_store),
) -> None:
    # 1. Authenticate BEFORE accepting the upgrade.
    try:
        identity = _verify_websocket_identity(websocket, token_store)
    except AuthenticationError:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    container: Any = None
    attach_socket: Any = None
    parser = StreamJsonParser()
    current_session_id: str | None = None
    session_started_emitted = False
    session_ended_emitted = False
    requested_session_id: str | None = None

    try:
        # 2. Load config + read the first client frame.
        config = load_config()
        try:
            first_frame = await websocket.receive_json()
        except (WebSocketDisconnect, ValueError):  # pragma: no cover — client race
            return

        if (
            not isinstance(first_frame, dict)
            or first_frame.get("type") != "user_message"
            or not isinstance(first_frame.get("content"), str)
        ):
            await _send_json_safe(
                websocket, {"type": "error", "reason": "bad_handshake"}
            )
            await websocket.close(code=4400)
            return

        first_content: str = first_frame["content"]
        new_session = bool(first_frame.get("new_session", False))

        if not new_session:
            claude_root = (
                Path(config.claude_users_root) / identity.user_id / ".claude"
            )
            recent = most_recent_session(claude_root, CWD)
            requested_session_id = recent.session_id if recent else None

        # 3. Start the container.
        bridge_env = {
            "AWS_REGION": os.environ.get("AWS_REGION", ""),
            "AWS_BEARER_TOKEN_BEDROCK": os.environ.get(
                "AWS_BEARER_TOKEN_BEDROCK", ""
            ),
        }
        try:
            container = await async_start_container(
                identity,
                image=DEFAULT_IMAGE,
                session_id=requested_session_id,
                bridge_env=bridge_env,
                config=config,
            )
        except BaseException:
            # Do not log the exception detail — it may quote env values.
            log.warning("container start failed")
            await _send_json_safe(
                websocket,
                {"type": "error", "reason": "container_start_failed"},
            )
            await websocket.close(code=1011)
            return

        try:
            attach_socket = await async_attach(container)
        except BaseException:
            log.warning("container attach failed")
            await _send_json_safe(
                websocket,
                {"type": "error", "reason": "container_start_failed"},
            )
            await websocket.close(code=1011)
            return

        # 4. Forward the first user message to Claude's stdin.
        try:
            attach_socket.send_stdin((first_content + "\n").encode("utf-8"))
        except Exception:
            log.debug("stdin write failed on first frame")

        # 5. Launch the client->container relay task.
        relay_task = asyncio.create_task(
            _relay_client_to_container(websocket, attach_socket)
        )

        try:
            # 6. Drive the container->client read loop.
            while True:
                frame = await _read_frame(attach_socket)
                if frame is None:
                    break
                stream_name, payload = frame
                if stream_name != "stdout":
                    # stderr is intentionally not forwarded; it can carry
                    # diagnostic strings we do not want to relay as-is.
                    continue
                events = parser.feed(payload)
                for event in events:
                    (
                        session_started_emitted,
                        session_ended_emitted,
                        current_session_id,
                    ) = await _dispatch_event(
                        websocket,
                        event,
                        session_started_emitted=session_started_emitted,
                        session_ended_emitted=session_ended_emitted,
                        current_session_id=current_session_id,
                        requested_session_id=requested_session_id,
                        parser=parser,
                    )

            # Clean EOF: flush parser + emit synthetic session_ended if none.
            for event in parser.flush():
                (
                    session_started_emitted,
                    session_ended_emitted,
                    current_session_id,
                ) = await _dispatch_event(
                    websocket,
                    event,
                    session_started_emitted=session_started_emitted,
                    session_ended_emitted=session_ended_emitted,
                    current_session_id=current_session_id,
                    requested_session_id=requested_session_id,
                    parser=parser,
                )

            if session_started_emitted and not session_ended_emitted:
                await _send_json_safe(
                    websocket,
                    {
                        "type": "session_ended",
                        "session_id": current_session_id,
                    },
                )
                session_ended_emitted = True
        finally:
            relay_task.cancel()
            try:
                await relay_task
            except (asyncio.CancelledError, Exception):  # pragma: no cover — race cleanup
                pass

    except asyncio.CancelledError:  # pragma: no cover — server-shutdown branch
        raise
    except WebSocketDisconnect:  # pragma: no cover — outer race
        pass
    except Exception:
        log.exception("unhandled error in ws bridge")
        await _send_json_safe(
            websocket, {"type": "error", "reason": "internal"}
        )
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=1011)
            except Exception:  # pragma: no cover — close-during-shutdown race
                pass
    finally:
        if attach_socket is not None:
            try:
                await asyncio.to_thread(attach_socket.close)
            except Exception:  # pragma: no cover — cleanup best-effort
                pass
        if container is not None:
            try:
                await async_stop_and_remove(container)
            except Exception:  # pragma: no cover — cleanup best-effort
                pass
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:  # pragma: no cover — already-closed race
                pass


async def _dispatch_event(
    websocket: WebSocket,
    event: StreamEvent,
    *,
    session_started_emitted: bool,
    session_ended_emitted: bool,
    current_session_id: str | None,
    requested_session_id: str | None,
    parser: StreamJsonParser,
) -> tuple[bool, bool, str | None]:
    """Emit the WS frames for a single parser event and update state."""
    # system/init: drives session_started + resume-mismatch ordering.
    if event.kind == "event":
        payload = event.payload or {}
        if (
            payload.get("type") == "system"
            and payload.get("subtype") == "init"
        ):
            actual = parser.session_id or payload.get("session_id")
            if isinstance(actual, str):
                current_session_id = actual
                if (
                    requested_session_id is not None
                    and requested_session_id != actual
                ):
                    await _send_json_safe(
                        websocket,
                        {
                            "type": "error",
                            "reason": "resume_failed",
                            "requested": requested_session_id,
                            "actual": actual,
                        },
                    )
                if not session_started_emitted:
                    await _send_json_safe(
                        websocket,
                        {
                            "type": "session_started",
                            "session_id": actual,
                        },
                    )
                    session_started_emitted = True
            return session_started_emitted, session_ended_emitted, current_session_id

    # All other events (assistant, tool_use, result, parser errors).
    for frame in stream_event_to_ws_frames(
        event, current_session_id=current_session_id
    ):
        await _send_json_safe(websocket, frame)
        if frame.get("type") == "session_ended":
            session_ended_emitted = True
    return session_started_emitted, session_ended_emitted, current_session_id


async def _relay_client_to_container(
    websocket: WebSocket, attach_socket: Any
) -> None:
    """Forward subsequent ``user_message`` frames from the client to stdin."""
    try:
        while True:
            frame = await websocket.receive_json()
            if not isinstance(frame, dict):
                continue
            if frame.get("type") != "user_message":
                continue
            content = frame.get("content")
            if not isinstance(content, str):
                continue
            try:
                await asyncio.to_thread(
                    attach_socket.send_stdin,
                    (content + "\n").encode("utf-8"),
                )
            except Exception:  # pragma: no cover — stdin race with cleanup
                return
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError, ValueError):
        return
