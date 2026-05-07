"""Report NExtSEEK session status — backing for the ``nextseek-session`` shim.

Reads ``session.json`` for the given env, computes the remaining TTL in
seconds, and returns a structured dict. Handles four cases:

* ``status=ok``       — session present and unexpired.
* ``status=ok`` with ``expired=True`` — session present but past its TTL.
* ``status=no-session`` — no session.json file on disk yet.
* ``status=corrupt``  — session.json exists but is unparseable.

Design decision DD-15 (task-02): the shim must be a pure read — it never
mutates cache state. Use ``nextseek-init --clear-cache`` to wipe the cache.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# CL-1: imports via ``from lib.X import ...``. The tests/conftest.py puts
# ``scripts/`` on sys.path so ``lib.*`` resolves at test time and runtime.
from lib.cache_paths import resolve_plugin_cache_base


def report_session(env: str, *, cache_base: Path | None = None) -> dict:
    """Return a structured report of the session for ``env``.

    Args:
        env: ``"dev"`` or ``"prod"``.
        cache_base: Optional base cache directory (without env suffix).
            Injected by tests to keep runs hermetic. When omitted the
            plugin cache base (honoring ``XDG_CACHE_HOME``) is used.

    Returns:
        Dict with one of three shapes:

        * Healthy / expired::

            {"status": "ok", "env": ..., "session_id": ...,
             "expires_at": ..., "remaining_ttl_seconds": int,
             "expired": bool, "cache_path": ...}

        * No session file yet::

            {"status": "no-session", "env": ..., "cache_path": ...}

        * Corrupt session.json::

            {"status": "corrupt", "env": ..., "cache_path": ..., "error": ...}
    """
    base = Path(cache_base) if cache_base is not None else resolve_plugin_cache_base()
    session_path = base / env / "session.json"
    if not session_path.exists():
        return {
            "status": "no-session",
            "env": env,
            "cache_path": str(session_path),
        }
    try:
        data = json.loads(session_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "corrupt",
            "env": env,
            "cache_path": str(session_path),
            "error": str(exc),
        }
    try:
        expires_at = datetime.fromisoformat(data["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "status": "corrupt",
            "env": env,
            "cache_path": str(session_path),
            "error": f"invalid expires_at: {exc}",
        }
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    remaining = int((expires_at - now).total_seconds())
    return {
        "status": "ok",
        "env": env,
        "session_id": data.get("session_id"),
        "expires_at": data["expires_at"],
        "remaining_ttl_seconds": remaining,
        "expired": remaining < 0,
        "cache_path": str(session_path),
    }


def _format_human(result: dict) -> str:
    lines = []
    for key, value in result.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``nextseek-session`` shim.

    Exit codes:
        0 — session exists and is NOT expired.
        1 — session expired, missing, or corrupt.
    """
    parser = argparse.ArgumentParser(
        prog="nextseek-session",
        description="Report NExtSEEK session status (TTL + expiry).",
    )
    parser.add_argument("--env", choices=["dev", "prod"], default="prod")
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the report as a JSON object on stdout.",
    )
    args = parser.parse_args(argv)

    result = report_session(args.env)

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_format_human(result))

    if result.get("status") == "ok" and not result.get("expired"):
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
