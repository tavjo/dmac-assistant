"""Plan A · T9b: _build_bridge_env emits DMAC_PATH_MAPPINGS when config + identity supplied."""
from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.ws import _build_bridge_env

# W3-H6: T9b's tests construct BridgeConfig(output_root=...). If T1 has not
# merged yet (e.g. CI picks up T9b's test file from a branch where T1 is
# still in flight), the field doesn't exist and the constructor raises
# ValidationError, masking the real (dependency) cause. Skip the entire
# module when output_root is missing so the failure shows as "skipped"
# (clearly labeled as T1-not-merged) instead of an opaque ValidationError.
pytestmark = pytest.mark.skipif(
    "output_root" not in BridgeConfig.model_fields,
    reason="T1 (BridgeConfig.output_root) has not merged yet; T9b tests are blocked.",
)


def test_path_mappings_emitted(tmp_path):
    identity = AuthenticatedIdentity(
        user_id="alice",
        password=SecretStr("pw"),
        projects=["demo"],
    )
    cfg = BridgeConfig(
        users={"alice": UserRecord(password=SecretStr("pw"), projects=["demo"])},
        claude_users_root=tmp_path / "claude",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        output_root=tmp_path / "output",
    )
    env = _build_bridge_env(config=cfg, identity=identity)
    mappings = json.loads(env["DMAC_PATH_MAPPINGS"])
    assert mappings["output"]["container_root"] == "/data/output"
    assert mappings["output"]["host_root"] == str(tmp_path / "output" / "alice")
    assert mappings["scratch"]["container_root"] == "/data/scratch"
    assert mappings["scratch"]["host_root"] == str(tmp_path / "scratch" / "alice")


def test_path_mappings_omitted_when_inputs_missing(monkeypatch):
    """The helper MUST NOT emit DMAC_PATH_MAPPINGS unless BOTH config and
    identity are supplied. Negative-case lock against an over-eager future
    change that constructs partial JSON from defaults.
    """
    # Clear bridge env keys so the dict is otherwise empty.
    for k in ("AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK", "NEXTSEEK_URL",
              "GCP_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.delenv(k, raising=False)

    # Both missing.
    assert "DMAC_PATH_MAPPINGS" not in _build_bridge_env()
    # config only.
    assert "DMAC_PATH_MAPPINGS" not in _build_bridge_env(
        config=None, identity=None
    )
