"""Authoritative server-side write gate (U-6, §8). Loaded once per request from the
canonical read_safe_endpoints.json (recon:chatNs §3). (endpoint, METHOD) tuple match
mirrors the pre-sidecar runner (recon:runner §1h)."""
from __future__ import annotations

import json
import os
from typing import Callable

from sidecar.app.ops import WriteBlockedError


class AllowlistMissingError(RuntimeError):
    """→ CONFIG_ERROR / exit 6."""


def _load_allowlist(path: str) -> set[tuple[str, str]]:
    if not os.path.exists(path):
        raise AllowlistMissingError(f"read_safe_endpoints.json missing at {path}")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    allow: set[tuple[str, str]] = set()
    for entry in data:
        ep = entry.get("endpoint")
        for m in entry.get("methods", []):
            allow.add((ep, m.upper()))
    return allow


def build_gate(cfg) -> Callable[[str, str | None, str | None, object], None]:
    allowlist = _load_allowlist(cfg.read_safe_endpoints_path)

    def gate(op: str, endpoint: str | None, method: str | None, confirmed_write: object) -> None:
        if op == "api-write":
            if confirmed_write is not True:  # strict: only boolean True confirms (§8)
                raise WriteBlockedError("api-write requires confirmed_write=true (server-side L2)")
            return
        if op == "api-read":
            if (endpoint, (method or "").upper()) not in allowlist:
                raise WriteBlockedError(
                    f"endpoint {endpoint!r} method {method!r} not in read_safe_endpoints.json")
            return
        # All other ops (entity/parse/graph/report/generate-submission) are read-class.
        return

    return gate
