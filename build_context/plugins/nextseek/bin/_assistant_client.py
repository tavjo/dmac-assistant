"""Typed httpx client for NExtSEEK's assistant viewset (U-3, OD-6). No chat_nextseek.

Auth = per-call user NS login as Basic (recon:nsApi §2 _check_auth accepts Basic).
Transport = POST query/async/ -> 202 AsyncQueryResponse, then GET tasks/{task_id}/progress/
polling until a terminal event (query_complete | query_error) appears in the progress list.
The assistant_prefix (with/without the i18n locale segment) is resolved by T0a.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from _assistant_models import (
    AsyncQueryResponse,
    QueryCompleteEvent,
    QueryErrorEvent,
    QueryRequest,
    SessionDetailResponse,
    TaskProgressResponse,
)

# Module-level sleep and monotonic clock so tests can monkeypatch them.
_sleep = time.sleep
_monotonic = time.monotonic

_DEFAULT_POLL_INTERVAL: float = 0.5


class AssistantClient:
    def __init__(self, *, base_url: str, assistant_prefix: str, auth: tuple[str, str],
                 timeout: float = 300.0, transport: httpx.BaseTransport | None = None,
                 poll_interval: float = _DEFAULT_POLL_INTERVAL) -> None:
        self._base = base_url.rstrip("/")
        self._prefix = assistant_prefix.strip("/")
        self._auth = auth
        self._timeout = timeout
        self._transport = transport
        self._poll_interval = poll_interval

    def _url(self, suffix: str) -> str:
        return f"{self._base}/{self._prefix}/{suffix.lstrip('/')}"

    def _client(self) -> httpx.Client:
        return httpx.Client(auth=self._auth, timeout=self._timeout, transport=self._transport)

    def run_query(self, query: str, *, mode: str, session_id: str | None = None,
                  force_new: bool = False,
                  on_event: Callable[[str, dict], None] | None = None,
                  ) -> tuple[dict, list[tuple[str, dict]]]:
        """POST query/async/ then poll tasks/{task_id}/progress/ until terminal.

        Returns (terminal_payload, [(event_name, data), ...]).
        The terminal_payload shapes are identical to the old SSE implementation:
          - query_complete: dict(data) from the progress event
          - query_error:    {"__error__": ..., "agent": ..., "session_id": ...}
          - no terminal:    {"__error__": "stream ended without terminal event", "agent": None}
        If on_event is provided, it is called for each new event as it arrives
        (incremental, no duplicates). Exceptions from on_event propagate.
        """
        body = QueryRequest(query=query, mode=mode,
                            session_id=session_id, force_new=force_new).model_dump(
                                mode="json", exclude_none=True)
        events: list[tuple[str, dict]] = []
        terminal: dict | None = None

        with self._client() as client:
            # Step 1: POST query/async/
            post_resp = client.post(self._url("query/async/"), json=body)
            post_resp.raise_for_status()
            async_resp = AsyncQueryResponse(**post_resp.json())
            task_id = str(async_resp.task_id)

            # Step 2: Poll loop
            seen_count = 0  # index into the append-only progress list
            deadline = _monotonic() + self._timeout

            while True:
                if _monotonic() >= deadline:
                    terminal = {"__error__": "stream ended without terminal event", "agent": None}
                    break

                progress_resp = client.get(self._url(f"tasks/{task_id}/progress/"))
                progress_resp.raise_for_status()
                task_progress = TaskProgressResponse(**progress_resp.json())

                # Process any new events since the last poll
                new_events = task_progress.progress[seen_count:]
                for pe in new_events:
                    name = pe.event
                    data = dict(pe.data)
                    events.append((name, data))
                    if on_event is not None:
                        on_event(name, data)
                    if name == "query_complete":
                        QueryCompleteEvent(**data)
                        terminal = dict(data)
                    elif name == "query_error":
                        QueryErrorEvent(**data)
                        terminal = {
                            "__error__": data.get("error", ""),
                            "agent": data.get("agent"),
                            "session_id": data.get("session_id"),
                        }
                seen_count = len(task_progress.progress)

                if terminal is not None:
                    break

                # Check if the task reached a terminal status without a terminal event
                # in progress (fallback: use result dict)
                if task_progress.status in ("completed", "error"):
                    result = task_progress.result
                    if result:
                        if task_progress.status == "error":
                            terminal = {
                                "__error__": str(result.get("error", "task ended with status=error")),
                                "agent": result.get("agent"),
                                "session_id": result.get("session_id"),
                            }
                        else:
                            terminal = dict(result)
                    else:
                        terminal = {"__error__": "stream ended without terminal event", "agent": None}
                    break

                _sleep(self._poll_interval)

        if terminal is None:
            terminal = {"__error__": "stream ended without terminal event", "agent": None}
        return terminal, events

    def session_detail(self, session_id: str, *, include_turns: bool = False) -> dict:
        params = {"include": "turns"} if include_turns else None
        with self._client() as client:
            r = client.get(self._url(f"sessions/{session_id}/"), params=params)
            r.raise_for_status()
            data = r.json()
            SessionDetailResponse(**data)
            return data

    def download_bundle(self, session_id: str, bundle_id: int) -> dict:
        with self._client() as client:
            r = client.get(self._url(f"sessions/{session_id}/bundles/{bundle_id}/"))
            r.raise_for_status()
            return r.json()

    def download_artifact(self, session_id: str, bundle_id: int, artifact_key: str) -> bytes:
        with self._client() as client:
            r = client.get(self._url(f"sessions/{session_id}/bundles/{bundle_id}/artifacts/{artifact_key}/"))
            r.raise_for_status()
            return r.content
