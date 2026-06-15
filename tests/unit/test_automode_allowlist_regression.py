"""Regression test: auto-mode allowlist is ``$defaults``-first and preserves all
three trusted-infra entries (NExtSEEK API / Neo4j / GCP).

This test is **always-on** — it guards against a near-miss where the OI-5 work
was almost regressed by a later edit that dropped these entries.

DD-8 conditional edit: the plan required modifying ``_automode_settings_args``
to add the Bedrock proxy host to the allowlist ONLY IF the T6 live acceptance
turn showed the auto-mode classifier blocking the proxy transport.
T6's committed verdict::

    tools/oi3-acceptance/runs/20260615T131344Z/classifier_verdict.json
    {"classifier_blocked_proxy": false, ...}

The classifier did NOT block.  Therefore no change to ``_automode_settings_args``
was made and T7 adds only this regression test.
"""
from __future__ import annotations

import json

from dmac_assistant.containers import _automode_settings_args

# Non-vacuous bridge_env: all three keys present with recognisable fake values.
_BRIDGE_ENV = {
    "NEXTSEEK_URL": "http://fake-ns:8000",
    "NEO4J_URI": "bolt://fake:7687",
    "GCP_API_KEY": "fake-gcp-key",
}


def _environment() -> list[str]:
    """Extract the ``autoMode.environment`` list from the production builder."""
    args = _automode_settings_args(_BRIDGE_ENV)
    # args == ["--settings", "<json>"]
    assert args[0] == "--settings", f"unexpected leading arg: {args[0]!r}"
    settings = json.loads(args[1])
    return settings["autoMode"]["environment"]


def test_defaults_first():
    """The ``environment`` list MUST lead with ``"$defaults"`` so built-in
    Claude Code trust rules are EXTENDED, not replaced (OI-5 invariant)."""
    env = _environment()
    assert env[0] == "$defaults", (
        f'"$defaults" must be the first entry; got {env[0]!r}'
    )


def test_nextseek_url_present():
    """A NExtSEEK trusted-infra entry referencing NEXTSEEK_URL must be present
    (non-vacuous: bridge_env explicitly contains NEXTSEEK_URL=http://fake-ns:8000)."""
    env = _environment()
    ns_url = _BRIDGE_ENV["NEXTSEEK_URL"]
    assert any(ns_url in entry for entry in env), (
        f"No entry containing {ns_url!r} found in autoMode.environment: {env}"
    )


def test_neo4j_uri_present():
    """A Neo4j trusted-infra entry referencing NEO4J_URI must be present
    (non-vacuous: bridge_env explicitly contains NEO4J_URI=bolt://fake:7687)."""
    env = _environment()
    neo4j_uri = _BRIDGE_ENV["NEO4J_URI"]
    assert any(neo4j_uri in entry for entry in env), (
        f"No entry containing {neo4j_uri!r} found in autoMode.environment: {env}"
    )


def test_gcp_api_key_present():
    """A GCP trusted-infra entry must be present when GCP_API_KEY is in the
    bridge_env (non-vacuous: bridge_env explicitly contains GCP_API_KEY)."""
    env = _environment()
    # The builder emits a prose sentence (not the raw key value) when GCP_API_KEY
    # is set; check for the stable keyword "Gemini" which appears in that sentence.
    assert any("Gemini" in entry or "GCP" in entry or "Google" in entry for entry in env), (
        f"No GCP/Gemini entry found in autoMode.environment: {env}"
    )


def test_all_three_present_and_defaults_first():
    """Conjunction guard: all four invariants hold in a single assertion so a
    future diff that drops any one entry fails immediately."""
    env = _environment()
    assert env[0] == "$defaults"
    ns_url = _BRIDGE_ENV["NEXTSEEK_URL"]
    neo4j_uri = _BRIDGE_ENV["NEO4J_URI"]
    assert any(ns_url in e for e in env), f"NEXTSEEK_URL entry missing: {env}"
    assert any(neo4j_uri in e for e in env), f"NEO4J_URI entry missing: {env}"
    assert any("Gemini" in e or "GCP" in e or "Google" in e for e in env), (
        f"GCP entry missing: {env}"
    )
