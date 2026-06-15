"""OI-3 T1 acceptance: drive the REAL proxy allowlist over a golden table.

Run from the repo root:

    uv run python tools/oi3-acceptance/validate_allowlist.py

This script imports the *actual* ``_allowed`` (and ``_is_canonical``) from the
hardened Bedrock proxy — it does NOT reimplement the allowlist — and runs them
over ``tools/oi3-acceptance/fixtures/allowlist_cases.json``. Each case is
``{"method", "path", "expect": "accept"|"deny"}``. The script:

  * Calls the real ``_allowed(method, path)`` on the LITERAL path string from the
    fixture (no HTTP client in the loop → immune to client path normalization;
    ``%2f`` / ``//`` / ``/./`` reach ``_allowed`` exactly as written).
  * Asserts the table contains a REQUIRED set of accept + canonicalization-bypass
    deny rows, so the table cannot be gamed by omitting hostile deny rows. A
    missing required row is a hard failure.
  * Prints a per-case PASS/FAIL line and exits 0 only if every verdict matches
    AND all required rows are present; exits non-zero otherwise.

IMPORT STRATEGY (hyphenated source dir)
---------------------------------------
The proxy lives under ``bedrock-proxy/`` (a hyphen → not importable as
``bedrock-proxy.app.proxy``). This is the IDENTICAL strategy used by
``tests/unit/test_bedrock_proxy.py``: put the ``bedrock-proxy`` directory on
``sys.path`` and import the generic ``app`` package from inside it. The proxy
dir is resolved from ``__file__`` relative to the repo root (NOT from cwd), so
the script works regardless of the working directory it is launched from.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root = .../dmac_assistant ; this file is at
# <repo>/tools/oi3-acceptance/validate_allowlist.py → parents[2] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_SRC = REPO_ROOT / "bedrock-proxy"
if str(PROXY_SRC) not in sys.path:
    sys.path.insert(0, str(PROXY_SRC))

# ``app`` here is ``bedrock-proxy/app`` (same as the test file). The real
# allowlist predicates — not a reimplementation.
from app.proxy import _allowed, _is_canonical  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "allowlist_cases.json"

# ---------------------------------------------------------------------------
# Required rows. The table MUST contain at least these (method, path, expect)
# triples or the run fails — this prevents gaming the result by dropping the
# canonicalization-bypass deny rows. Verdicts are still checked against the REAL
# ``_allowed`` for every row in the file, required or not.
# ---------------------------------------------------------------------------
_ALLOWED_MODEL = "us.anthropic.claude-opus-4-8"
REQUIRED_ROWS: set[tuple[str, str, str]] = {
    # --- ACCEPT (the three canonical routes) ---
    ("GET", "/inference-profiles", "accept"),
    ("POST", f"/model/{_ALLOWED_MODEL}/invoke", "accept"),
    ("POST", f"/model/{_ALLOWED_MODEL}/invoke-with-response-stream", "accept"),
    # --- DENY (canonicalization-bypass + policy attempts; >= 7 required) ---
    ("GET", "/inference-profiles-evil", "deny"),
    ("POST", f"//model/{_ALLOWED_MODEL}/invoke", "deny"),
    ("POST", f"/model/./{_ALLOWED_MODEL}/invoke", "deny"),
    ("POST", f"/model/{_ALLOWED_MODEL}%2finvoke", "deny"),
    ("POST", f"/model/us.anthropic.claude-other/invoke-with-response-stream", "deny"),
    ("POST", f"/model/{_ALLOWED_MODEL}/converse", "deny"),
    ("PUT", f"/model/{_ALLOWED_MODEL}/invoke", "deny"),
}


def _load_cases() -> list[dict]:
    if not FIXTURE.exists():
        print(f"FAIL: fixture not found: {FIXTURE}", file=sys.stderr)
        sys.exit(2)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        print(f"FAIL: fixture {FIXTURE} has no non-empty 'cases' list", file=sys.stderr)
        sys.exit(2)
    return cases


def main() -> int:
    cases = _load_cases()

    print(f"validate_allowlist: importing real _allowed from {PROXY_SRC}/app/proxy.py")
    print(f"validate_allowlist: {len(cases)} case(s) from {FIXTURE.name}")
    print(f"validate_allowlist: _is_canonical importable = {callable(_is_canonical)}")
    print("-" * 72)

    present: set[tuple[str, str, str]] = set()
    failures = 0

    for case in cases:
        method = case["method"]
        path = case["path"]
        expect = case["expect"]
        if expect not in ("accept", "deny"):
            print(f"FAIL  (bad-expect) {method:6} {path!r} expect={expect!r}")
            failures += 1
            continue

        present.add((method, path, expect))

        # Drive the REAL allowlist on the literal path string.
        verdict_bool = _allowed(method, path)
        verdict = "accept" if verdict_bool else "deny"
        ok = verdict == expect
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{status}  {method:6} {path!r}  expect={expect:6} got={verdict}")

    print("-" * 72)

    # Required-rows gate: every required (method, path, expect) must be present.
    missing = sorted(REQUIRED_ROWS - present)
    if missing:
        print(f"FAIL: {len(missing)} required row(s) absent from the table:")
        for method, path, expect in missing:
            print(f"  MISSING  {method:6} {path!r}  (expect={expect})")
        failures += 1

    if failures:
        print(f"\nRESULT: FAIL — {failures} problem(s)")
        return 1

    print(
        f"\nRESULT: PASS — all {len(cases)} verdict(s) matched and "
        f"all {len(REQUIRED_ROWS)} required row(s) present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
