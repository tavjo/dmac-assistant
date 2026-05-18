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
    are PRESERVED as empty strings to keep blast radius zero. NEXTSEEK_BASE_URL
    is DERIVED from NEXTSEEK_URL (T0.3 F-T0.3-2 hardener; mirrors entrypoint.sh:14)
    and emits empty string only when BOTH are unset. New keys (GCP_API_KEY /
    NEO4J_*) are skip-if-empty.
    """
    for k in ("GCP_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
              "NEO4J_DATABASE",
              "AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK", "NEXTSEEK_URL",
              "NEXTSEEK_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    # New keys: omitted when unset.
    assert "GCP_API_KEY" not in env
    assert "NEO4J_URI" not in env
    assert "NEO4J_USER" not in env
    assert "NEO4J_PASSWORD" not in env
    assert "NEO4J_DATABASE" not in env
    # Legacy keys: ALWAYS present (passthrough preserved), as empty strings
    # when unset. This matches the OLD inline literal's behavior at
    # ws.py:274-280 and is the W3-C2 R2 fix.
    assert env["AWS_REGION"] == ""
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == ""
    assert env["NEXTSEEK_URL"] == ""
    # NEXTSEEK_BASE_URL: ALWAYS present (derivation contract), empty string
    # when BOTH NEXTSEEK_BASE_URL and NEXTSEEK_URL are unset on the host.
    # See test_nextseek_base_url_derived_from_nextseek_url_when_unset for
    # the populated-derivation case.
    assert env["NEXTSEEK_BASE_URL"] == ""


def test_nextseek_base_url_forwarded_when_explicitly_set(monkeypatch):
    """T0.3: chat_nextseek.config.ChatConfig reads NEXTSEEK_BASE_URL directly
    with no NEXTSEEK_URL fallback. When the host env has NEXTSEEK_BASE_URL
    set explicitly, it passes through verbatim (overriding the NEXTSEEK_URL
    derivation fallback).
    """
    monkeypatch.setenv("NEXTSEEK_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("NEXTSEEK_URL", "https://other.example.com")
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["NEXTSEEK_BASE_URL"] == "https://api.example.com"


def test_nextseek_base_url_derived_from_nextseek_url_when_unset(monkeypatch):
    """T0.3 F-T0.3-2 hardener: locked source spec line 125 mandates derivation,
    not passthrough. The typical bridge-host deployment has NEXTSEEK_URL set
    but NEXTSEEK_BASE_URL unset (the alias is an entrypoint-internal convention).
    `_build_bridge_env` must mirror `entrypoint.sh:14` `: ${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}`
    so docker exec (which bypasses the entrypoint per DD-04) still sees a
    populated NEXTSEEK_BASE_URL.
    """
    monkeypatch.delenv("NEXTSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("NEXTSEEK_URL", "https://nx.mit.edu")
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["NEXTSEEK_BASE_URL"] == "https://nx.mit.edu"
    # And the original NEXTSEEK_URL is still emitted unchanged (sanity check).
    assert env["NEXTSEEK_URL"] == "https://nx.mit.edu"


def test_nextseek_base_url_empty_when_both_unset(monkeypatch):
    """T0.3: when BOTH NEXTSEEK_BASE_URL and NEXTSEEK_URL are unset, the
    derivation yields empty string and the key is still emitted (matching the
    legacy tuple's always-emitted contract enforced by test_unset_keys_omitted).
    """
    monkeypatch.delenv("NEXTSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("NEXTSEEK_URL", raising=False)
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["NEXTSEEK_BASE_URL"] == ""


def test_neo4j_database_forwarded(monkeypatch):
    """T0.3: chat_nextseek reads NEO4J_DATABASE for entity-graph queries.
    Forwarded skip-if-empty — same pattern as NEO4J_URI/USER/PASSWORD.
    """
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j-prod")
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert env["NEO4J_DATABASE"] == "neo4j-prod"


def test_neo4j_database_omitted_when_unset(monkeypatch):
    """T0.3: NEO4J_DATABASE is skip-if-empty. Unset means absent from dict
    (membership-checks in containers.py rely on this).
    """
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    from dmac_assistant.ws import _build_bridge_env
    env = _build_bridge_env()
    assert "NEO4J_DATABASE" not in env
