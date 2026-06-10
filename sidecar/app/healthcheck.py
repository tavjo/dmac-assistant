"""Semantic healthcheck (spec §11): config loads, allowlist loads, MySQL reachable.

Read-only by construction: the only DB statement issued is SELECT 1.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        from sidecar.app.config import SidecarConfig
        cfg = SidecarConfig.from_env()
        with open(cfg.read_safe_endpoints_path, encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list) or not entries:
            print("allowlist empty or malformed", file=sys.stderr)
            return 1
        import mysql.connector

        conn = mysql.connector.connect(
            host=cfg.session_db["host"], port=cfg.session_db["port"],
            user=cfg.session_db["user"], password=cfg.session_db["password"],
            database=cfg.session_db["database"], connection_timeout=5,
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
        finally:
            conn.close()
        return 0
    except Exception as exc:  # noqa: BLE001 — healthcheck must never crash the prober
        print(f"unhealthy: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
