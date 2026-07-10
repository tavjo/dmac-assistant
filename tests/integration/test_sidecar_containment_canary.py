"""Gate 1 — shared-credential containment, BOUND to a functioning 9-op run.

Threat model (the hostile-host case): even when every one of the 16 shared
credentials IS present in the bridge's `bridge_env` (e.g. a misconfigured or
compromised host that still has GCP/Neo4j/MySQL/SESSION_DB creds in its
environment), the production `_build_environment` / `_build_exec_environment`
path MUST NOT forward any of them into the per-user agent container. We seed
`bridge_env` with distinct CANARY sentinel VALUES for all 16 keys, spawn the
agent via the real `start_container` (with `config.sidecar_network` set), drive
ALL 9 NS ops to success IN THAT SAME container, then scan that container's
surfaces for any sentinel.

The conjunction is the gate (vet findings 9 + 16): containment is only meaningful
if the de-credentialed container can STILL do all 9 ops (it reaches the sidecar /
viewset, which hold the real creds). A container that leaks nothing because it can
do nothing does not pass.

Two halves:
  * `test_build_env_strips_all_shared_canaries` — the deterministic host-side half
    (no docker): the bridge env builders drop all 16 even when bridge_env carries
    them. Runs in the hermetic suite.
  * `test_decredentialed_agent_runs_9_ops_with_zero_shared_creds` — the live
    conjunction (docker + live stack + paid LLM/NS calls).
"""
from __future__ import annotations

import json

import pytest

from dmac_assistant.containers import _build_environment, _build_exec_environment
from tests.harness.canaries import scan_for_canaries
from tests.harness.containers import docker_available

from tests.integration import _sidecar_e2e_helpers as H


# Distinct per-key sentinel VALUES (not the literal "CANARY") so a partial-deletion
# bug that drops some keys but not others is caught per-key. Keys are the canonical
# 16 shared-cred keys (tools/e2e/run_headless.py::SHARED_CRED_KEYS).
SHARED_CANARY: dict[str, str] = {
    "GCP_API_KEY": "CANARY-GCP-zzz01",
    "NEO4J_URI": "CANARY-NEOURI-zzz02",
    "NEO4J_USER": "CANARY-NEOUSER-zzz03",
    "NEO4J_PASSWORD": "CANARY-NEOPASS-zzz04",
    "NEO4J_DATABASE": "CANARY-NEODB-zzz05",
    "MYSQL_HOST_DEV": "CANARY-MYSHOST-zzz06",
    "MYSQL_PORT": "CANARY-MYSPORT-zzz07",
    "MYSQL_USER": "CANARY-MYSUSER-zzz08",
    "MYSQL_DEV_PASSWORD": "CANARY-MYSPASS-zzz09",
    "SESSION_DB_TYPE": "CANARY-SDBTYPE-zzz10",
    "SESSION_DB_HOST": "CANARY-SDBHOST-zzz11",
    "SESSION_DB_PORT": "CANARY-SDBPORT-zzz12",
    "SESSION_DB_USER": "CANARY-SDBUSER-zzz13",
    "SESSION_DB_PASSWORD": "CANARY-SDBPASS-zzz14",
    "SESSION_DB_NAME": "CANARY-SDBNAME-zzz15",
    "SESSION_DB_PATH": "CANARY-SDBPATH-zzz16",
}
_ALL_CANARY_VALUES = list(SHARED_CANARY.values())

# The auto-mode `--settings` allowlist (OI-5, built by `_automode_settings_args`)
# LEGITIMATELY embeds the Neo4j ENDPOINT URI into a "trusted internal infra"
# descriptor on the CC exec cmdline — this is shipped, documented behavior (project
# CLAUDE.md "Headless Invocation":  `--settings '{"autoMode":{"environment":
# ["$defaults", <trusted NS API / Neo4j / GCP entries>]}}'`). The endpoint URL is NOT
# a usable credential on its own: NEO4J_USER / NEO4J_PASSWORD are stripped from BOTH
# the container env AND the settings descriptor. So the settings-surface scan targets
# the 15 SECRET values that must NEVER ride the cmdline (passwords, hosts, ports, db
# names/paths, the GCP key value); the one legitimately-forwarded endpoint is
# excluded here and positively asserted present below (it proves the allowlist works).
# NOTE (escalated, T12 review): that the literal Neo4j endpoint URI is visible to the
# agent via its own `claude --settings` argv is an OI-5 design tradeoff, not a leak of
# a secret — flagged for conscious ratification; see the T12 remediation report.
_SETTINGS_SECRET_CANARY_VALUES = [
    v for k, v in SHARED_CANARY.items() if k != "NEO4J_URI"
]


def _seeded_bridge_env() -> dict[str, str]:
    """A hostile-host bridge_env: all 16 shared canaries PLUS the legitimately
    forwarded basics. Injecting MYSQL_*/SESSION_DB_* directly proves the builders
    DELETE them (they are never collected by _build_bridge_env, so absence alone
    would not prove the deletion path)."""
    return {
        **SHARED_CANARY,
        "AWS_REGION": "us-east-1",
        "AWS_BEARER_TOKEN_BEDROCK": "ABSK-not-a-canary",
        "NEXTSEEK_URL": H.AGENT_NEXTSEEK_URL,
        "DMAC_PATH_MAPPINGS": "/data/scratch/demo=>~/out",
    }


def test_build_env_strips_all_shared_canaries() -> None:
    """Host-side deterministic half of gate 1 (no docker required)."""
    identity = H.make_identity("demo", "pw-not-a-canary")
    bridge_env = _seeded_bridge_env()

    base = _build_environment(
        identity, bridge_env, bedrock_proxy_url="http://bedrock-proxy:8080"
    )
    exec_ns = _build_exec_environment(
        identity, bridge_env, route="ns",
        bedrock_proxy_url="http://bedrock-proxy:8080",
    )
    exec_cc = _build_exec_environment(
        identity, bridge_env, route="cc",
        bedrock_proxy_url="http://bedrock-proxy:8080",
    )

    for label, env in (("base", base), ("exec_ns", exec_ns), ("exec_cc", exec_cc)):
        # No shared-cred KEY survives ...
        leaked_keys = [k for k in SHARED_CANARY if k in env]
        assert leaked_keys == [], f"{label}: shared-cred keys not stripped: {leaked_keys}"
        # ... and no shared-cred VALUE appears in ANY value (catches re-keying).
        hits = scan_for_canaries([json.dumps(env)], paths=[], canaries=_ALL_CANARY_VALUES)
        assert hits == [], f"{label}: shared canary value leaked: {hits}"

    # Positive control: the legitimately-forwarded NEXTSEEK_URL DID make it through,
    # so the test is proving selective stripping, not a blanket empty env.
    assert base.get("NEXTSEEK_URL") == H.AGENT_NEXTSEEK_URL


@pytest.mark.skipif(not docker_available(), reason="docker daemon not available")
@pytest.mark.skipif(
    not H.nextseek_backend_available(),
    reason="local NExtSEEK backend (nextseek_nginx) not running",
)
@pytest.mark.live_docker
@pytest.mark.slow
def test_decredentialed_agent_runs_9_ops_with_zero_shared_creds(
    sidecar_up_session, ns_creds, tmp_path
) -> None:
    """Live conjunction: 9 ops succeed in a de-cred container that leaks no canary."""
    api_user, api_pass = ns_creds
    identity = H.make_identity(api_user, api_pass)
    config = H.make_bridge_config(tmp_path, staging_root=tmp_path / "sidecar-staging")
    bridge_env = _seeded_bridge_env()

    container = H.start_decred_agent(identity, config, bridge_env)
    try:
        # Sanity: the canaries are genuinely NOT in the running container's env.
        env_dump = H.exec_in_agent(container, ["env"]).stdout
        proc_dump = H.exec_in_agent(
            container, ["cat", "/proc/1/environ"]).stdout

        H.warm_sidecar(container)
        run = H.run_nine_ops(container)
        # The auto-mode `--settings '{"autoMode":...}'` JSON rides the CC exec cmdline
        # (NOT the container env), so the scan must cover it for the SAME bridge_env the
        # canary seeds — built by the real production builder `_automode_settings_args`.
        run.settings = H.settings_surface(bridge_env)

        scratch_dump = H.exec_in_agent(
            container, ["sh", "-c", "cat /data/scratch/* 2>/dev/null || true"]).stdout

        # --- CONTAINMENT (the gate) -----------------------------------------
        # Container-resident surfaces (env, /proc/1/environ, scratch, all 9 ops'
        # frames incl. the query/plan viewset frames) must carry NONE of the 16 shared
        # canaries — full-strength scan.
        streams = [env_dump, proc_dump, scratch_dump, *run.frames]
        hits = scan_for_canaries(streams, paths=[], canaries=_ALL_CANARY_VALUES)
        assert hits == [], f"shared canary leaked into agent surfaces: {hits}"

        # The auto-mode `--settings` JSON rides the CC exec CMDLINE (not env), so it is
        # a distinct exfil surface that the env scan above cannot see. Scan it for the
        # 15 SECRET canaries that `_automode_settings_args` must never embed (a password
        # or the GCP key re-keyed into an allowlist descriptor would be caught here).
        settings_hits = scan_for_canaries(
            [run.settings], paths=[], canaries=_SETTINGS_SECRET_CANARY_VALUES)
        assert settings_hits == [], (
            f"secret canary leaked into the --settings allowlist cmdline: {settings_hits}"
        )
        # Positive control: the ONE legitimately-forwarded value (the Neo4j endpoint
        # URI) IS present — proving the OI-5 allowlist descriptor was built, so the
        # secret-only scan above is selective, not a vacuous empty-string scan.
        assert SHARED_CANARY["NEO4J_URI"] in run.settings, (
            "OI-5 Neo4j allowlist descriptor missing from --settings; the scan would "
            "be vacuous (settings string built from the wrong bridge_env?)."
        )
        assert len(run.results) == 9, f"expected 9 ops, drove {len(run.results)}"
        by_name = {r.name: r for r in run.results}

        # --- NON-VACUITY: ALL 9 ops genuinely FUNCTION (vet finding 9/16) -----
        # Containment is meaningful precisely because the de-credentialed container
        # does real work (real Gemini/Neo4j/NS calls via the sidecar) — it is not an
        # inert container that "leaks nothing because it does nothing".
        # Amendment A-4 (2026-06-11): query + plan now succeed (the A-3 mirror models
        # were reconciled with the LOCAL stack's query_complete shape — bundle_id +
        # files added as optional), so the full 9-op conjunction is restored. The old
        # query/plan exit-4 contract-mismatch tripwire is retired by this amendment.
        all_ops = ["entity", "parse", "graph", "api-read", "api-write",
                   "report", "generate-submission", "query", "plan"]
        failed_ops = [r for r in run.results if r.name in all_ops and not r.ok]
        assert not failed_ops, (
            "ops did not function (containment would be vacuous): "
            + "; ".join(f"{r.name}=exit{r.exit_code} {r.stderr.strip()[-160:]}"
                        for r in failed_ops)
        )
        # Step 2 contract: each op returned its typed shape (not just exit 0).
        # query + plan terminate on a validated query_complete event whose terminal
        # payload carries `reply` (the A-4-reconciled QueryCompleteEvent shape).
        for name, required_key in (
            ("entity", "sampletypes"), ("parse", "mode"), ("graph", "cypher"),
            ("api-read", "response"), ("api-write", "response"),
            ("report", "saved_files"), ("generate-submission", "report"),
            ("query", "reply"), ("plan", "reply"),
        ):
            payload = by_name[name].terminal_json()
            assert required_key in payload, (
                f"{name} contract missing {required_key!r}; got keys {list(payload)}"
            )
    finally:
        from dmac_assistant.containers import stop_and_remove
        stop_and_remove(container)
