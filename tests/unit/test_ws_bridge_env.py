"""Plan A · T9: _build_bridge_env reads bridge env vars (no DMAC_PATH_MAPPINGS yet)."""
from __future__ import annotations


def test_existing_keys_preserved(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "tok")
    monkeypatch.setenv("NEXTSEEK_URL", "https://nx.mit.edu")
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["AWS_REGION"] == "us-east-1"
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == "tok"
    assert env["NEXTSEEK_URL"] == "https://nx.mit.edu"


def test_gcp_api_key(monkeypatch):
    monkeypatch.setenv("GCP_API_KEY", "test-key")
    from dmac_assistant.ws import _build_bridge_env
    assert _build_bridge_env().get("GCP_API_KEY") == "test-key"


def test_neo4j_creds(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://nx:7687")
    monkeypatch.setenv("NEO4J_USER", "neo")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["NEO4J_URI"] == "bolt://nx:7687"
    assert env["NEO4J_USER"] == "neo"
    assert env["NEO4J_PASSWORD"] == "secret"


def test_unset_keys_omitted(monkeypatch):
    """W3-C2: legacy keys (AWS_REGION/AWS_BEARER_TOKEN_BEDROCK/NEXTSEEK_URL)
    are PRESERVED as empty strings to keep blast radius zero. New keys
    (GCP_API_KEY / NEO4J_*) are skip-if-empty.
    """
    for k in ("GCP_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
              "AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK", "NEXTSEEK_URL"):
        monkeypatch.delenv(k, raising=False)
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    # New keys: omitted when unset.
    assert "GCP_API_KEY" not in env
    assert "NEO4J_URI" not in env
    assert "NEO4J_USER" not in env
    assert "NEO4J_PASSWORD" not in env
    # Legacy keys: ALWAYS present (passthrough preserved), as empty strings
    # when unset. This matches the OLD inline literal's behavior at
    # ws.py:274-280 and is the W3-C2 R2 fix.
    assert env["AWS_REGION"] == ""
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == ""
    assert env["NEXTSEEK_URL"] == ""
