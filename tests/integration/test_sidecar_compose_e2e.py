"""Sidecar compose-E2E gates (T12): per-user isolation (2), server-side write
refusal (3), staging->sweep->publish same turn (6/7), sidecar-unavailable +
bad-credential fail-fast (7/8), staging cleanup + janitor (12), no host ports (15).

The 9-op functional-E2E + the gate-1 containment conjunction live in
test_sidecar_containment_canary.py (one paid 9-op run, not duplicated here).

Run: `make sidecar-up && uv run pytest tests/integration/test_sidecar_compose_e2e.py \
      tests/integration/test_sidecar_containment_canary.py -m live_docker -v -p no:xdist`
"""
from __future__ import annotations

import types
import uuid

import pytest

from tests.harness.containers import docker_available
from tests.integration import _sidecar_e2e_helpers as H

pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
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


# ----------------------------------------------------- gate 2: per-user isolation

def test_per_user_isolation(tmp_path) -> None:
    """Gate 2: two users -> distinct hashed session keys + staging dirs; neither
    can read the other's staged artifacts. Exercises the REAL hashing + sweep
    functions (sha256(api_user)), not a mock."""
    from sidecar.app.contract import NsLogin
    from sidecar.app.sessions import _session_key
    from sidecar.app.staging import make_stage
    from dmac_assistant.staging_sweep import sweep_sidecar_staging

    staging_root = tmp_path / "staging"
    scratch_root = tmp_path / "scratch"
    staging_root.mkdir()
    scratch_root.mkdir()

    user_a, user_b = "alice", "bob"
    # Distinct session keys (U-5 keying = ns:{sha256(api_user)}).
    assert _session_key(user_a) != _session_key(user_b)

    cfg = types.SimpleNamespace(staging_dir=str(staging_root))
    src = tmp_path / "artifact_a.csv"
    src.write_text("col\nval\n")
    req_a = "11111111-1111-4111-8111-111111111111"
    stage_a = make_stage(cfg, NsLogin(api_user=user_a, api_pass="x"), req_a)
    out_a = stage_a("report", {"saved_files": {"k": str(src)}})
    assert out_a["staged_files"], "alice's artifact was not staged"

    # alice's and bob's staging dirs differ (distinct hashed roots).
    a_dirs = {p.name for p in staging_root.iterdir()}
    assert len(a_dirs) == 1  # only alice's hash so far

    # bob's sweep sees NOTHING (his hash dir does not exist).
    (scratch_root / user_b).mkdir()
    swept_b = sweep_sidecar_staging(
        staging_root=staging_root, scratch_root=scratch_root,
        user_id=user_b, api_user=user_b,
    )
    assert swept_b == set(), "bob swept alice's artifacts — isolation breach"

    # alice's own sweep DOES see her artifact.
    (scratch_root / user_a).mkdir()
    swept_a = sweep_sidecar_staging(
        staging_root=staging_root, scratch_root=scratch_root,
        user_id=user_a, api_user=user_a,
    )
    assert swept_a, "alice could not retrieve her own staged artifact"


# ------------------------------------------ gate 6/7: stage -> sweep -> publish

def test_staging_sweep_publish_same_turn_real_artifact(tmp_path) -> None:
    """Gate 6/7: a REAL sidecar-staged artifact is swept into scratch AND published
    to the user's output dir in ONE turn, through the production wiring with NO
    monkeypatch of `_sweep_then_diff`.

    Why a test-seeded artifact (not a live report-op artifact): the local NExtSEEK
    stack is data-empty, so the only artifact-emitting op (report) returns empty
    `saved_files` (verified live this session). We therefore feed a real file to the
    REAL sidecar `staging.make_stage`, then run the EXACT production sequence the WS
    handler runs (`ws._sweep_then_diff` -> `dispatch_post_turn_copy`) — every line of
    the `# pragma: no cover` router-on sweep+publish wiring executes against a genuine
    staged artifact. A fully live report-op-driven version is escalated as needing
    sample data on the target stack (see T12 report)."""
    from sidecar.app.contract import NsLogin
    from sidecar.app.staging import make_stage
    from dmac_assistant import ws as ws_module
    from dmac_assistant.ws import dispatch_post_turn_copy

    user = "demo"
    staging_root = tmp_path / "sidecar-staging"
    config = H.make_bridge_config(tmp_path, staging_root=staging_root)
    (config.scratch_root / user).mkdir(parents=True, exist_ok=True)
    (config.output_root / user).mkdir(parents=True, exist_ok=True)
    identity = H.make_identity(user, "pw")

    # 1) the sidecar stages a real artifact (real production make_stage).
    src = tmp_path / "report.xlsx"
    src.write_bytes(b"PK\x03\x04 fake-but-real-bytes")
    cfg = types.SimpleNamespace(staging_dir=str(staging_root))
    req_id = str(uuid.uuid4())
    stage = make_stage(cfg, NsLogin(api_user=user, api_pass="x"), req_id)
    staged = stage("report", {"saved_files": {"report": str(src)}})
    assert staged["staged_files"], "make_stage did not stage the artifact"

    # 2) the bridge's REAL post-turn sequence (ws.py:489-498): sweep then publish.
    #    pre_turn_files is the scratch snapshot taken at turn start (empty here — the
    #    artifact is still in staging, not scratch).
    pre_turn = ws_module.snapshot_scratch_files(config.scratch_root, identity.user_id)
    after, new = ws_module._sweep_then_diff(config, identity, pre_turn)
    assert new, "sweep produced no new files for publication"
    dispatch_post_turn_copy(
        scratch_root=config.scratch_root, output_root=config.output_root,
        user_id=user, new_files=new,
    )

    # 3) the artifact is in scratch AND published to output IN THE SAME TURN.
    scratch_hits = list((config.scratch_root / user).rglob("report.xlsx"))
    output_hits = list((config.output_root / user).rglob("report.xlsx"))
    assert scratch_hits, "artifact not swept into scratch"
    assert output_hits, "artifact not published to output dir same turn"
    assert output_hits[0].read_bytes() == src.read_bytes(), "published bytes differ"

    # gate 12 (first half): after the sweep, the staging request dir + marker are gone.
    user_hash_dirs = list(staging_root.iterdir()) if staging_root.exists() else []
    leftover_req = [p for d in user_hash_dirs for p in d.glob(req_id)]
    leftover_marker = [p for d in user_hash_dirs for p in d.glob(f"{req_id}.complete")]
    assert not leftover_req, f"staging request dir not cleaned: {leftover_req}"
    assert not leftover_marker, f"completion marker not cleaned: {leftover_marker}"


# ----------------------------------------- gate 12: abandoned-dir janitor path

def test_abandoned_dir_not_swept_and_cleaned(tmp_path) -> None:
    """Gate 12 (second half): a staging request dir WITHOUT a `.complete` marker is
    never swept (partial-write safety) and is removed by the janitor (cleanup_request)."""
    from sidecar.app.staging import _user_hash, cleanup_request
    from dmac_assistant.staging_sweep import sweep_sidecar_staging

    user = "demo"
    staging_root = tmp_path / "staging"
    scratch_root = tmp_path / "scratch"
    (scratch_root / user).mkdir(parents=True)
    base = staging_root / _user_hash(user)
    abandoned_req = "22222222-2222-4222-8222-222222222222"
    abandoned = base / abandoned_req
    abandoned.mkdir(parents=True)
    (abandoned / "partial.csv").write_text("incomplete\n")
    # NOTE: no `<req>.complete` marker written.

    swept = sweep_sidecar_staging(
        staging_root=staging_root, scratch_root=scratch_root,
        user_id=user, api_user=user,
    )
    assert swept == set(), "abandoned (markerless) dir was swept — partial-write leak"
    assert abandoned.is_dir(), "abandoned dir removed by sweep (only the janitor should)"

    cfg = types.SimpleNamespace(staging_dir=str(staging_root))
    cleanup_request(cfg, user, abandoned_req)
    assert not abandoned.exists(), "janitor did not remove the abandoned dir"


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
