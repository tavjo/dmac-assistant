"""OI-3 de-cred before/after capture for `_build_environment`.

Run with:  uv run python tools/oi3-acceptance/capture_baseline.py

Produces (and self-verifies):
    tools/oi3-acceptance/runs/baseline/build_env_after.txt   (JSON)

The committed "before" snapshot
`tools/oi3-acceptance/runs/baseline/build_env_before.txt` is the historical
PRE-T4 evidence that `_build_environment` USED TO forward
`AWS_BEARER_TOKEN_BEDROCK` into every agent container. It is left BYTE-FOR-BYTE
intact by this script — do NOT regenerate it.

After T4, `_build_environment` de-credentials the agent container: it takes a
REQUIRED `bedrock_proxy_url`, points Claude Code at the proxy
(`ANTHROPIC_BEDROCK_BASE_URL` + `CLAUDE_CODE_SKIP_BEDROCK_AUTH=1`) and NO
LONGER forwards the bearer token even when `bridge_env` carries it. This script
captures that post-T4 output as `build_env_after.txt` and self-verifies the
token is ABSENT — the diff `build_env_before.txt` -> `build_env_after.txt` is
the de-credentialing proof. No real secret value is written -- the fixture
token is a placeholder per R-8.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src/ is on sys.path so this script can be invoked directly via
# `uv run python tools/oi3-acceptance/capture_baseline.py` from the project
# root without requiring the caller to set PYTHONPATH.
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.containers import _build_environment

# ---------------------------------------------------------------------------
# Fixture: mirrors _MINIMUM_BRIDGE_ENV from tests/unit/test_containers.py.
# The bearer token is supplied as an INPUT on purpose -- it is what the de-cred
# guard must filter, so the absence check below is NON-VACUOUS.
# PLACEHOLDER values only -- R-8 forbids real secrets in committed files.
# ---------------------------------------------------------------------------
BRIDGE_ENV: dict[str, str] = {
    "AWS_REGION": "us-east-1",
    "AWS_BEARER_TOKEN_BEDROCK": "bearer-abc",  # placeholder -- NOT a real token
}

IDENTITY = AuthenticatedIdentity(
    user_id="alice",
    password=SecretStr("s3cret"),  # placeholder
    projects=["proj-a"],
)

# Placeholder proxy URL (matches the compose / config default); R-8: not a secret.
BEDROCK_PROXY_URL = "http://bedrock-proxy:8080"

# ---------------------------------------------------------------------------
# Call _build_environment with its CURRENT (post-T4) signature. The required
# bedrock_proxy_url kw param has no default -- a missed thread would TypeError.
# ---------------------------------------------------------------------------
env: dict[str, str] = _build_environment(
    IDENTITY, BRIDGE_ENV, bedrock_proxy_url=BEDROCK_PROXY_URL
)

# ---------------------------------------------------------------------------
# Write the post-T4 "after" snapshot. The committed "before" snapshot is the
# historical PRE-T4 evidence and is intentionally NOT touched here.
# ---------------------------------------------------------------------------
AFTER = Path(__file__).parent / "runs" / "baseline" / "build_env_after.txt"
AFTER.parent.mkdir(parents=True, exist_ok=True)
AFTER.write_text(json.dumps(env, sort_keys=True, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Self-verify the de-credentialing: the bearer token must be ABSENT from the
# produced env (and its value must not be re-keyed under another name), while
# the proxy wiring must be present. Exit non-zero on any deviation.
# ---------------------------------------------------------------------------
loaded: dict[str, str] = json.loads(AFTER.read_text(encoding="utf-8"))
problems: list[str] = []
if "AWS_BEARER_TOKEN_BEDROCK" in loaded:
    problems.append("AWS_BEARER_TOKEN_BEDROCK still present in produced env mapping")
if BRIDGE_ENV["AWS_BEARER_TOKEN_BEDROCK"] in loaded.values():
    problems.append("bearer token VALUE re-keyed under a different env key")
if loaded.get("ANTHROPIC_BEDROCK_BASE_URL") != BEDROCK_PROXY_URL:
    problems.append("ANTHROPIC_BEDROCK_BASE_URL not pointed at the proxy")
if loaded.get("CLAUDE_CODE_SKIP_BEDROCK_AUTH") != "1":
    problems.append("CLAUDE_CODE_SKIP_BEDROCK_AUTH != '1'")
if loaded.get("CLAUDE_CODE_USE_BEDROCK") != "1":
    problems.append("CLAUDE_CODE_USE_BEDROCK != '1'")

if problems:
    print("FAIL: de-cred capture did not hold:", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    sys.exit(1)

print(f"de-cred capture OK — wrote {AFTER}")
print("  AWS_BEARER_TOKEN_BEDROCK absent from agent env (was present pre-T4)")
print(f"  ANTHROPIC_BEDROCK_BASE_URL={loaded['ANTHROPIC_BEDROCK_BASE_URL']!r}")
print(f"  Keys captured: {sorted(loaded.keys())}")
