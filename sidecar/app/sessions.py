"""Per-user session store (U-5, §9). Key = ns:{sha256(api_user)}[:conv] so granular
ops get user-scoped continuity and assistant/conversation calls stay per-conversation.
Uses the existing MySQLSessionState(db_config, session_id) (recon:chatNs §2).

(The assistant_session_id suffix is symmetry-only and not wired into any live path in
this plan; NExtSEEK owns conversation continuity via QueryRequest.session_id.)"""
from __future__ import annotations

import hashlib
from typing import Any

from sidecar.app.contract import NsLogin


def _session_key(api_user: str, assistant_session_id: str | None = None) -> str:
    base = "ns:" + hashlib.sha256(api_user.encode("utf-8")).hexdigest()
    return f"{base}:{assistant_session_id}" if assistant_session_id else base


def make_session(
    login: NsLogin,
    config: Any,
    sidecar_cfg: Any,
    assistant_session_id: str | None = None,
) -> Any:
    from chat_nextseek.session import MySQLSessionState

    key = _session_key(login.api_user, assistant_session_id)
    return MySQLSessionState(sidecar_cfg.session_db, key)
