"""T0 baseline capture: prove AWS_BEARER_TOKEN_BEDROCK is forwarded by _build_environment.

Run with:  uv run python tools/oi3-acceptance/capture_baseline.py

Produces:  tools/oi3-acceptance/runs/baseline/build_env_before.txt  (JSON)

The output file is committed as the "before" baseline for the OI-3 de-cred diff (T4).
No real secret value is written -- fixture token is a placeholder per R-8.
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
# PLACEHOLDER value only -- R-8 forbids real secrets in committed files.
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

# ---------------------------------------------------------------------------
# Call _build_environment with its CURRENT signature (pre-T4 -- no
# bedrock_proxy_url parameter yet).  Signature as of T0:
#   _build_environment(identity, bridge_env, *, runtime_mode=None) -> dict[str, str]
# ---------------------------------------------------------------------------
env: dict[str, str] = _build_environment(IDENTITY, BRIDGE_ENV)

# ---------------------------------------------------------------------------
# Write sorted JSON to the baseline file.
# ---------------------------------------------------------------------------
OUT = (
    Path(__file__).parent / "runs" / "baseline" / "build_env_before.txt"
)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(env, sort_keys=True, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Self-verify: assert the key is present (exit non-zero if not).
# ---------------------------------------------------------------------------
loaded: dict[str, str] = json.loads(OUT.read_text(encoding="utf-8"))
if "AWS_BEARER_TOKEN_BEDROCK" not in loaded:
    print(
        "FAIL: AWS_BEARER_TOKEN_BEDROCK not found in produced env mapping.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"baseline OK — wrote {OUT}")
print(f"  AWS_BEARER_TOKEN_BEDROCK present: value={loaded['AWS_BEARER_TOKEN_BEDROCK']!r}")
print(f"  Keys captured: {sorted(loaded.keys())}")
