"""Plan A · T2: container environment must include GCP_API_KEY + NEO4J_*
and redact secret keys in repr() and model_dump()."""
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
    return BridgeConfig(
        users={"alice": UserRecord(password=SecretStr("pw"), projects=["demo"])},
        claude_users_root=tmp_path / "claude",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        output_root=tmp_path / "output",
    )


def test_gcp_api_key_passed_through(tmp_path):
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={"GCP_API_KEY": "key-123"})
    assert spec.environment["GCP_API_KEY"] == "key-123"


def test_neo4j_creds_passed_through(tmp_path):
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={
            "NEO4J_URI": "bolt://nx:7687",
            "NEO4J_USER": "neo",
            "NEO4J_PASSWORD": "n4j",
        })
    assert spec.environment["NEO4J_URI"] == "bolt://nx:7687"
    assert spec.environment["NEO4J_USER"] == "neo"
    assert spec.environment["NEO4J_PASSWORD"] == "n4j"


def test_neo4j_creds_optional(tmp_path):
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None, bridge_env={})
    assert "NEO4J_URI" not in spec.environment
    assert "NEO4J_PASSWORD" not in spec.environment


def test_redacted_env_keys_includes_neo4j_password_and_gcp():
    assert "NEO4J_PASSWORD" in _REDACTED_ENV_KEYS
    assert "GCP_API_KEY" in _REDACTED_ENV_KEYS


def test_repr_redacts_neo4j_password(tmp_path):
    """M1: redaction must actually fire in repr(), not just be in the set."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"NEO4J_PASSWORD": "secret-neo4j-value"})
    text = repr(spec)
    assert "secret-neo4j-value" not in text
    assert "<REDACTED>" in text


def test_model_dump_redacts_gcp_api_key(tmp_path):
    """M1: model_dump() must also redact."""
    spec = build_container_spec(_identity(), _config(tmp_path),
        image="t:1", session_id=None,
        bridge_env={"GCP_API_KEY": "secret-gcp-value"})
    dumped = spec.model_dump()
    assert dumped["environment"]["GCP_API_KEY"] == "<REDACTED>"
