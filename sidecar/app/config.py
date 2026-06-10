"""Sidecar configuration. All credential I/O flows through this object.

The sidecar is the sole holder of shared creds (spec U-1). chat_nextseek reads its
own env (recon:chatNs §4), so SidecarConfig validates presence/shape for the
sidecar's OWN needs (session DB, staging, allowlist path, port) and leaves
chat_nextseek's env keys (GCP_API_KEY, NEO4J_*, MYSQL_*) in the process env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class SidecarConfigError(RuntimeError):
    """Maps to error code CONFIG_MISSING / exit 2 at the protocol layer."""


_REQUIRED = (
    "SESSION_DB_HOST", "SESSION_DB_USER",
    "SESSION_DB_PASSWORD", "SESSION_DB_NAME",
    "SIDECAR_STAGING_DIR", "READ_SAFE_ENDPOINTS_PATH",
)


@dataclass(frozen=True)
class SidecarConfig:
    session_db: dict = field(repr=False)
    staging_dir: str
    read_safe_endpoints_path: str
    ws_port: int = 8765

    def __repr__(self) -> str:
        return (
            f"SidecarConfig(session_db={{'host': {self.session_db['host']!r}, "
            f"'password': 'REDACTED'}}, staging_dir={self.staging_dir!r}, "
            f"ws_port={self.ws_port})"
        )

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        missing = [k for k in _REQUIRED if not os.environ.get(k)]
        if missing:
            raise SidecarConfigError(f"missing required env: {missing}")
        return cls(
            session_db={
                "host": os.environ["SESSION_DB_HOST"],
                "port": int(os.environ.get("SESSION_DB_PORT", "3306")),
                "user": os.environ["SESSION_DB_USER"],
                "password": os.environ["SESSION_DB_PASSWORD"],
                "database": os.environ["SESSION_DB_NAME"],
            },
            staging_dir=os.environ["SIDECAR_STAGING_DIR"],
            read_safe_endpoints_path=os.environ["READ_SAFE_ENDPOINTS_PATH"],
            ws_port=int(os.environ.get("SIDECAR_WS_PORT", "8765")),
        )
