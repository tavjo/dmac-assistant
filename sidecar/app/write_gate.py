"""Authoritative server-side write gate (U-6, §8). Loaded once per request from the
canonical read_safe_endpoints.json (recon:chatNs §3). (endpoint, METHOD) tuple match
mirrors the pre-sidecar runner (recon:runner §1h)."""
from __future__ import annotations

import json
from typing import Callable

from sidecar.app.contract import SIDECAR_OPS
from sidecar.app.ops import WriteBlockedError

# Read-class ops: every SIDECAR_OPS member that is neither "api-read" nor "api-write".
# Derived from the contract so there is a single source of truth.
_READ_CLASS = frozenset(SIDECAR_OPS) - {"api-read", "api-write"}


class AllowlistMissingError(RuntimeError):
    """→ CONFIG_ERROR / exit 6."""


def _load_allowlist(path: str) -> set[tuple[str, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise AllowlistMissingError(
            f"read_safe_endpoints.json unusable at {path}: {type(exc).__name__}"
        ) from exc
    if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
        raise AllowlistMissingError(
            f"read_safe_endpoints.json malformed at {path}"
        )
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
        if op in _READ_CLASS:
            # entity/parse/graph/report/generate-submission are read-class — always allow.
            return None
        # Default-deny: any op label that is not in SIDECAR_OPS is a programming error.
        raise WriteBlockedError(f"unknown op for write gate: {op!r}")

    return gate
