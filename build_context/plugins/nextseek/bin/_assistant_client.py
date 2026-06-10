"""Typed httpx client for NExtSEEK's assistant viewset (U-3, OD-6). No chat_nextseek.

Auth = per-call user NS login as Basic (recon:nsApi §2 _check_auth accepts Basic).
SSE wire = `event: <type>\\ndata: <json>\\n\\n`; stream terminates on close
(recon:nsApi §2 — no explicit done event). Terminal = query_complete | query_error.
The assistant_prefix (with/without the i18n locale segment) is resolved by T0a.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from _assistant_models import (
    QueryCompleteEvent,
    QueryErrorEvent,
    QueryRequest,
    SessionDetailResponse,
)


class AssistantClient:
    def __init__(self, *, base_url: str, assistant_prefix: str, auth: tuple[str, str],
                 timeout: float = 300.0, transport: httpx.BaseTransport | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._prefix = assistant_prefix.strip("/")
        self._auth = auth
        self._timeout = timeout
        self._transport = transport

    def _url(self, suffix: str) -> str:
        return f"{self._base}/{self._prefix}/{suffix.lstrip('/')}"

    def _client(self) -> httpx.Client:
        return httpx.Client(auth=self._auth, timeout=self._timeout, transport=self._transport)

    def run_query(self, query: str, *, mode: str, session_id: str | None = None,
                  force_new: bool = False) -> tuple[dict, list[tuple[str, dict]]]:
        """POST /query/ (SSE). Returns (terminal_payload, [(event_name, data), ...])."""
        body = QueryRequest(query=query, mode=mode,
                            session_id=session_id, force_new=force_new).model_dump(mode="json", exclude_none=True)
        events: list[tuple[str, dict]] = []
        terminal: dict | None = None
        with self._client() as client:
            with client.stream("POST", self._url("query/"), json=body) as resp:
                resp.raise_for_status()
                for name, data in _iter_sse(resp.iter_lines()):
                    events.append((name, data))
                    if name == "query_complete":
                        QueryCompleteEvent(**data)
                        terminal = dict(data)
                    elif name == "query_error":
                        QueryErrorEvent(**data)
                        terminal = {"__error__": data.get("error", ""), "agent": data.get("agent"),
                                    "session_id": data.get("session_id")}
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


def _iter_sse(lines):
    """GENERATOR: yield (event_name, json_data) per SSE event as lines arrive."""
    event_name = "message"
    for line in lines:
        if line == "":
            event_name = "message"
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            raw = line[len("data:"):].strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield (event_name, data)
