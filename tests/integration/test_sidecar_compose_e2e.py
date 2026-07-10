"""Sidecar compose-E2E gates (T12): per-user isolation (2), server-side write
refusal (3), staging->sweep->publish same turn (6/7), sidecar-unavailable +
bad-credential fail-fast (7/8), staging cleanup + janitor (12), no host ports (15).

The 9-op functional-E2E + the gate-1 containment conjunction live in
test_sidecar_containment_canary.py (one paid 9-op run, not duplicated here).

Run: `make sidecar-up && uv run pytest tests/integration/test_sidecar_compose_e2e.py \
      tests/integration/test_sidecar_containment_canary.py -m live_docker -v -p no:xdist`
"""
from __future__ import annotations

import uuid

import pytest

from tests.harness.containers import docker_available
from tests.integration import _sidecar_e2e_helpers as H

pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.skipif(
        not H.nextseek_backend_available(),
        reason="local NExtSEEK backend (nextseek_nginx) not running",
    ),
    pytest.mark.live_docker,
    pytest.mark.slow,
]


# --------------------------------------------------------------- gate 15: no ports

def test_no_host_ports_real_container_name(sidecar_up_session) -> None:
    """Gate 15: the sidecar publishes NO host port (reachable only on the Docker
    network). Inspect the REAL compose-derived container name, not the service DNS
    name 'nextseek-sidecar' (decided seam)."""
    bindings = H.sidecar_inspect_port_bindings()
    assert bindings in (None, {}), f"sidecar leaked host port bindings: {bindings!r}"


# NOTE: gate 2 (per-user isolation), gate 6/7 (stage->sweep->publish), and gate 12
# (abandoned-dir janitor) are PURE host-side (no docker/live sidecar) and were moved
# to tests/integration/test_sidecar_staging_isolation.py so they run in the hermetic
# suite instead of being hidden behind this module's live_docker/slow/docker gating.


# ----------------------------- gate 3: server-side write refusal (raw WS bypass)

def test_server_side_write_refusal_raw_frame(sidecar_up_session, ns_creds, tmp_path) -> None:
    """Gate 3: the SERVER is the hard floor. Send raw WS frames that bypass the
    advisory client checks -> WRITE_BLOCKED, independent of any client guard."""
    api_user, api_pass = ns_creds
    identity = H.make_identity(api_user, api_pass)
    config = H.make_bridge_config(tmp_path, staging_root=tmp_path / "sidecar-staging")
    bridge_env = {"NEXTSEEK_URL": H.AGENT_NEXTSEEK_URL}
    container = H.start_decred_agent(identity, config, bridge_env)
    try:
        login = {"api_user": api_user, "api_pass": api_pass}
        # api-write WITHOUT confirmed_write reaching the server (advisory client check
        # bypassed by crafting the frame directly) -> WRITE_BLOCKED.
        resp = H.raw_ws_frame_via_agent(container, {
            "op": "api-write",
            "args": {"parser_plan": "{\"target_endpoint\": \"/nextseek_api/samples/\"}"},
            "ns_login": login,
            "request_id": str(uuid.uuid4()),
        })
        assert resp.get("status") == "error", f"unconfirmed write not refused: {resp}"
        assert resp["error"]["code"] == "WRITE_BLOCKED", resp

        # api-read against a NON-allowlisted endpoint -> WRITE_BLOCKED at the server gate.
        resp2 = H.raw_ws_frame_via_agent(container, {
            "op": "api-read",
            "args": {"parser_plan":
                     "{\"target_endpoint\": \"/nextseek_api/admin/users/\"}"},
            "ns_login": login,
            "request_id": str(uuid.uuid4()),
        })
        assert resp2.get("status") == "error", f"non-allowlisted read not refused: {resp2}"
        assert resp2["error"]["code"] == "WRITE_BLOCKED", resp2
    finally:
        from dmac_assistant.containers import stop_and_remove
        stop_and_remove(container)


# ---------------------------- gate 7/8: sidecar-unavailable + bad-credential

def test_sidecar_unreachable_fail_fast(sidecar_up_session, ns_creds, tmp_path) -> None:
    """Gate 7: a granular op against an unreachable sidecar fails FAST with
    TRANSPORT_ERROR / exit 7 — no hang. Pointed at a closed port on the sidecar host
    so the connection is refused immediately (equivalent to the sidecar being down for
    that op, without tearing down the shared session sidecar)."""
    api_user, api_pass = ns_creds
    identity = H.make_identity(api_user, api_pass)
    config = H.make_bridge_config(tmp_path, staging_root=tmp_path / "sidecar-staging")
    container = H.start_decred_agent(identity, config, {"NEXTSEEK_URL": H.AGENT_NEXTSEEK_URL})
    try:
        res = H.exec_in_agent(
            container, [f"{H._BIN}/nextseek-entity-extract", "--query", "x"],
            env={"NEXTSEEK_SIDECAR_PORT": "9"},  # discard port -> connection refused
            timeout=60,  # must return well under this; fail-fast, no hang
        )
        assert res.exit_code == 7, f"expected exit 7 (TRANSPORT_ERROR), got {res.exit_code}: {res.stderr}"
        assert "TRANSPORT_ERROR" in res.stderr, res.stderr
    finally:
        from dmac_assistant.containers import stop_and_remove
        stop_and_remove(container)


def test_bad_credentials_per_family(sidecar_up_session, ns_creds, tmp_path) -> None:
    """Gate 8: bad NS credentials are handled DIFFERENTLY per family — only the
    viewset short-circuits to AUTH_FAILED / exit 8.

    Observed-live taxonomy (T12 verified against the local stack):
      * viewset query/plan -> AUTH_FAILED / exit 8 (the assistant viewset returns
        401 on the POST; the A-3 async client maps 401 -> AUTH_FAILED).
      * granular sidecar ops -> the op SUCCEEDS at the transport level (exit 0) and
        the downstream 401 is carried INSIDE the response payload
        (`response.status_code == 401`), because chat_nextseek's
        `tool_nextseek_api_request` returns the 401 as data rather than raising.
        So granular ops are NOT mapped to AUTH_FAILED/8 — the per-family
        distinction this gate proves.

    NOTE (escalation): the W3 post-wave note predicted granular bad-creds ->
    AGENT_FAILED/exit 4 (assuming a *raising* downstream). On this stack no granular
    op raises on a 401 — all soft-return it as payload (entity/parse/graph/
    generate-submission don't even touch the user's NS REST creds; api-read/api-write/
    report embed the 401). The load-bearing containment property (bad creds never
    map to AUTH_FAILED on the granular family, and never leak the password) holds; the
    exit-4 prediction does not. Flagged as a taxonomy follow-up, not weakened here."""
    api_user, _ = ns_creds
    identity = H.make_identity(api_user, "definitely-the-wrong-password")
    config = H.make_bridge_config(tmp_path, staging_root=tmp_path / "sidecar-staging")
    container = H.start_decred_agent(identity, config, {"NEXTSEEK_URL": H.AGENT_NEXTSEEK_URL})
    try:
        # granular op (allowlisted GET /projects/) with wrong creds: transport OK
        # (exit 0), 401 embedded in the response payload, NOT AUTH_FAILED/8.
        gran = H.exec_in_agent(
            container, [f"{H._BIN}/nextseek-api-read", "--parser-plan",
                        "{\"target_endpoint\": \"/nextseek_api/projects/\"}"],
            timeout=120)
        assert gran.exit_code != 8, (
            f"granular bad-cred must NOT map to AUTH_FAILED/8; got {gran.exit_code}: {gran.stderr}"
        )
        assert gran.exit_code == 0, (
            f"granular bad-cred expected soft exit 0 with embedded 401; got "
            f"{gran.exit_code}: {gran.stderr}"
        )
        assert "401" in gran.stdout, (
            f"granular op did not carry the downstream 401 in its payload: {gran.stdout[:300]}"
        )
        # the password must not appear in the surfaced output (redaction).
        assert "definitely-the-wrong-password" not in (gran.stdout + gran.stderr)

        # viewset op with wrong creds -> AUTH_FAILED / 8, redacted.
        vs = H.exec_in_agent(
            container, [f"{H._BIN}/nextseek-query", "--json", "--query",
                        "how many samples"], timeout=120)
        assert vs.exit_code == 8, (
            f"viewset bad-cred expected exit 8 (AUTH_FAILED), got {vs.exit_code}: {vs.stderr}"
        )
        assert "AUTH_FAILED" in vs.stderr, vs.stderr
        assert "definitely-the-wrong-password" not in (vs.stdout + vs.stderr)
    finally:
        from dmac_assistant.containers import stop_and_remove
        stop_and_remove(container)
