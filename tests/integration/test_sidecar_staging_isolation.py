"""Hermetic sidecar staging/isolation gates (T12), split out of the live compose-E2E.

These three gates are PURE host-side: they exercise the real sidecar staging +
sweep + janitor functions (`sidecar.app.staging`, `sidecar.app.sessions`,
`dmac_assistant.staging_sweep`, `dmac_assistant.ws`) against `tmp_path` artifacts
with NO docker daemon, NO live sidecar, and NO paid LLM/NS calls. They were moved
out of `test_sidecar_compose_e2e.py` (whose module-level `live_docker`/`slow`/docker
skipif would have hidden them) so they run in the deterministic hermetic suite.

Gates covered:
  * gate 2  — per-user isolation (distinct hashed session keys + staging dirs);
  * gate 6/7 — stage -> sweep -> publish in ONE turn through the production wiring;
  * gate 12 — abandoned (markerless) staging dir never swept + janitor removes it.

Behavior is identical to the originals; only the location + the absence of the
live_docker gating changed.
"""
from __future__ import annotations

import types
import uuid

from tests.integration import _sidecar_e2e_helpers as H


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
