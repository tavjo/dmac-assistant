"""One-shot probe: is the lab MySQL (SESSION_DB_*) reachable from a Docker network?

Runs a throwaway python:3.14-slim container on a temp bridge network and attempts a
SELECT 1 against SESSION_DB_HOST. Read-only. Names only — never prints secrets.
Usage: uv run python tools/probe_session_db.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from dotenv import load_dotenv

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    host = os.environ.get("SESSION_DB_HOST")
    port = os.environ.get("SESSION_DB_PORT", "3306")
    user = os.environ.get("SESSION_DB_USER")
    pw = os.environ.get("SESSION_DB_PASSWORD")
    db = os.environ.get("SESSION_DB_NAME")
    if not all([host, user, pw, db]):
        print("missing SESSION_DB_* in .env (HOST/USER/PASSWORD/NAME)", file=sys.stderr)
        return 2
    # one-shot container with mysql-connector; values passed via -e (not echoed)
    code = (
        "import mysql.connector,sys\n"
        "c=mysql.connector.connect(host=sys.argv[1],port=int(sys.argv[2]),user=sys.argv[3],"
        "password=sys.argv[4],database=sys.argv[5],connection_timeout=8)\n"
        "cur=c.cursor();cur.execute('SELECT 1');cur.fetchall();print('SESSION_DB_REACHABLE')"
    )
    r = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "python:3.14-slim",
            "sh",
            "-c",
            "pip install --quiet mysql-connector-python >/dev/null 2>&1 && "
            f'python -c "{code}" "$0" "$1" "$2" "$3" "$4"',
            host,
            port,
            user,
            pw,
            db,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    ok = "SESSION_DB_REACHABLE" in r.stdout
    print(r.stdout.strip() or "(no stdout)")
    if not ok:
        # stderr may name the failure class (timeout/refused/auth) — safe to show the class only
        print(f"NOT REACHABLE: {r.stderr.strip()[:300]}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
