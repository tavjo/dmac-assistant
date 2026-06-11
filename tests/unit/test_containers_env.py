"""T11 (inverts Plan A · T2): the agent container environment must NOT
include GCP_API_KEY / NEO4J_* (sidecar-held shared creds, U-1) and must
still redact secret keys in repr() and model_dump()."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import _REDACTED_ENV_KEYS, build_container_spec


def _identity():
    return AuthenticatedIdentity(
        user_id="alice",
        password=SecretStr("pw"),
        projects=["demo"],
    )


def _config(tmp_path: Path) -> BridgeConfig:
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={"alice": UserRecord(password=SecretStr("pw"), projects=["demo"])},
        claude_users_root=tmp_path / "claude",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        output_root=tmp_path / "output",
        catalog_file=catalog,
    )


def test_gcp_api_key_not_forwarded(tmp_path):
    """T11 (U-1): GCP_API_KEY is sidecar-held; it must never reach the
    agent container even when present in bridge_env."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={"GCP_API_KEY": "key-123"})
    assert "GCP_API_KEY" not in spec.environment


def test_neo4j_creds_not_forwarded(tmp_path):
    """T11 (U-1): NEO4J_* are sidecar-held; absent even when in bridge_env."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={
            "NEO4J_URI": "bolt://nx:7687",
            "NEO4J_USER": "neo",
            "NEO4J_PASSWORD": "n4j",
        })
    assert "NEO4J_URI" not in spec.environment
    assert "NEO4J_USER" not in spec.environment
    assert "NEO4J_PASSWORD" not in spec.environment


def test_neo4j_creds_absent_unconditionally(tmp_path):
    """The old optional-when-unset case is now the always-true case."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={})
    assert "NEO4J_URI" not in spec.environment
    assert "NEO4J_PASSWORD" not in spec.environment


def test_redacted_env_keys_includes_neo4j_password_and_gcp():
    assert "NEO4J_PASSWORD" in _REDACTED_ENV_KEYS
    assert "GCP_API_KEY" in _REDACTED_ENV_KEYS


def test_dmac_path_mappings_passed_through(tmp_path):
    """Wave-3 closure (Amendment 8) H1: T9b's DMAC_PATH_MAPPINGS must be
    forwarded by _build_environment, not silently dropped."""
    mapping = '{"output":{"container_root":"/data/output","host_root":"/h/o"}}'
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"DMAC_PATH_MAPPINGS": mapping})
    assert spec.environment["DMAC_PATH_MAPPINGS"] == mapping


def test_dmac_path_mappings_redacted_in_repr(tmp_path):
    """Wave-3 closure (Amendment 8) M1: DMAC_PATH_MAPPINGS encodes host
    filesystem layout; must be redacted from repr()/model_dump() per R-03."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"DMAC_PATH_MAPPINGS": '{"host_root":"/sensitive/path"}'})
    text = repr(spec)
    assert "/sensitive/path" not in text
    dumped = spec.model_dump()
    assert dumped["environment"]["DMAC_PATH_MAPPINGS"] == "<REDACTED>"


def test_neo4j_password_value_never_in_repr(tmp_path):
    """T11: NEO4J_PASSWORD is no longer forwarded, so its value must appear
    nowhere in repr(); redaction must still fire for forwarded secrets
    (NEXTSEEK_PASSWORD from the identity)."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"NEO4J_PASSWORD": "secret-neo4j-value"})
    text = repr(spec)
    assert "NEO4J_PASSWORD" not in spec.environment
    assert "secret-neo4j-value" not in text
    assert "<REDACTED>" in text  # NEXTSEEK_PASSWORD still redacts


def test_gcp_api_key_value_never_in_model_dump(tmp_path):
    """T11: GCP_API_KEY is no longer forwarded, so it must be absent from
    model_dump()'s environment entirely (containment beats redaction)."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"GCP_API_KEY": "secret-gcp-value"})
    dumped = spec.model_dump()
    assert "GCP_API_KEY" not in dumped["environment"]
    assert "secret-gcp-value" not in repr(dumped)
    # M1 regression: model_dump() still redacts forwarded secrets.
    assert dumped["environment"]["NEXTSEEK_PASSWORD"] == "<REDACTED>"


def test_data_output_mounted_ro(tmp_path):
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={})
    expected_host = str(tmp_path / "output" / "alice")
    assert expected_host in spec.volumes
    assert spec.volumes[expected_host] == {"bind": "/data/output", "mode": "ro"}


def test_no_mount_path_collisions(tmp_path):
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={})
    binds = [v["bind"] for v in spec.volumes.values()]
    assert "/data/output" in binds
    assert "/data/scratch" in binds
    assert len(binds) == len(set(binds))
