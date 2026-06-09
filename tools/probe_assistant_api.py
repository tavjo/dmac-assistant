"""One-shot probe: is the NExtSEEK assistant viewset live, and at which base path?

Read-only. Auth = the user's own NS login (Basic). Never prints secret values.
Usage: uv run python tools/probe_assistant_api.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import httpx
from dotenv import load_dotenv

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CANDIDATE_PREFIXES = ("nextseek_api/assistant", "en/nextseek_api/assistant")


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    base = (os.environ.get("NEXTSEEK_URL") or "").rstrip("/")
    user = os.environ.get("NEXTSEEK_USERNAME")
    password = os.environ.get("NEXTSEEK_PASSWORD")
    if not (base and user and password):
        print("missing NEXTSEEK_URL/NEXTSEEK_USERNAME/NEXTSEEK_PASSWORD in .env", file=sys.stderr)
        return 2

    results: dict[str, dict] = {}
    with httpx.Client(timeout=20.0, auth=(user, password), follow_redirects=False) as client:
        for prefix in CANDIDATE_PREFIXES:
            url = f"{base}/{prefix}/me/"
            try:
                r = client.get(url)
                body: object
                try:
                    body = r.json()
                except ValueError:
                    body = r.text[:200]
                results[prefix] = {"url": url, "status": r.status_code, "body": body}
            except httpx.HTTPError as exc:
                results[prefix] = {"url": url, "error": type(exc).__name__}

    print(json.dumps(results, indent=2, default=str))
    live = [
        p
        for p, r in results.items()
        if r.get("status") == 200
        and isinstance(r.get("body"), dict)
        and "username" in r["body"]
    ]
    if live:
        print(f"\nASSISTANT_BASE_PATH={live[0]}")
        return 0
    print(
        "\nNo candidate path returned a valid /me/ response — assistant viewset "
        "NOT deployed on this server (or auth/permission failed; check status codes above).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
