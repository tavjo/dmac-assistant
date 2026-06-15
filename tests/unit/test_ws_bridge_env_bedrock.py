"""OI-3 (T4): the bridge no longer reads or forwards AWS_BEARER_TOKEN_BEDROCK.

``ws._build_bridge_env`` assembles the env the bridge hands the in-container
Claude Code from the bridge's PROCESS environment. After T4 the institutional
bearer token lives only in the Bedrock proxy sidecar's compose env_file, so the
bridge must NOT emit ``AWS_BEARER_TOKEN_BEDROCK`` into bridge_env — even when
the host process env carries it (the non-vacuous case: the token is present on
the host but is dropped on the way out).
"""
from __future__ import annotations


def test_build_bridge_env_omits_bearer_token_when_host_has_it(monkeypatch):
    """Non-vacuous: the host env CARRIES the token; bridge_env must not."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "host-bearer-tok")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    from dmac_assistant.ws import _build_bridge_env

    env = _build_bridge_env()

    assert "AWS_BEARER_TOKEN_BEDROCK" not in env
    # the token VALUE must not be re-keyed under some other name either
    assert "host-bearer-tok" not in "".join(env.values())
    # positive control: a legitimately-forwarded legacy key DID survive, so the
    # absence above is selective stripping, not a vacuous empty env.
    assert env["AWS_REGION"] == "us-east-1"


def test_build_bridge_env_omits_bearer_token_when_host_lacks_it(monkeypatch):
    """The key is gone from the always-emitted legacy contract entirely."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    from dmac_assistant.ws import _build_bridge_env

    env = _build_bridge_env()

    assert "AWS_BEARER_TOKEN_BEDROCK" not in env
