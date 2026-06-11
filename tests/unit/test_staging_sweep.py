"""T10 (OD-2, §10): sweep the sidecar's hashed-user staging dir into the user's
scratch. Includes the staging-hash parity pin: the sweep must look in EXACTLY
the directory `sidecar.app.staging` writes to (silent hash drift = artifacts
never published, with no automated catch until live E2E)."""
import hashlib
from pathlib import Path

import pytest

from dmac_assistant.staging_sweep import sweep_sidecar_staging


def _stage(staging_root: Path, api_user: str, request_id: str,
           files: dict[str, str]) -> Path:
    """Lay out a completed staged request the way the sidecar does."""
    base = staging_root / hashlib.sha256(api_user.encode("utf-8")).hexdigest()
    req_dir = base / request_id
    req_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        dst = req_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)
    (base / f"{request_id}.complete").write_text("")
    return base


def test_sweep_copies_completed_request_into_scratch(tmp_path):
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    base = _stage(staging, "alice", "req-1", {"report.xlsx": "data"})

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    dst = scratch / "alice" / "nextseek-artifacts" / "report.xlsx"
    assert dst.is_file() and dst.read_text() == "data"
    assert written == {"nextseek-artifacts/report.xlsx"}
    # cleanup after sweep (gate 12): request dir + marker are gone
    assert not (base / "req-1").exists()
    assert not (base / "req-1.complete").exists()


def test_sweep_preserves_nested_structure(tmp_path):
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    _stage(staging, "alice", "req-2", {"sub/dir/plot.png": "png"})

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert written == {"nextseek-artifacts/sub/dir/plot.png"}
    assert (scratch / "alice" / "nextseek-artifacts" / "sub" / "dir" / "plot.png").is_file()


def test_partial_request_without_marker_is_not_swept(tmp_path):
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    base = staging / hashlib.sha256(b"alice").hexdigest()
    req_dir = base / "req-partial"
    req_dir.mkdir(parents=True)
    (req_dir / "half.xlsx").write_text("incomplete")
    # NO .complete marker

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert written == set()
    assert (req_dir / "half.xlsx").exists()  # left in place for a later sweep
    assert not (scratch / "alice").exists()


def test_orphan_marker_without_dir_is_removed(tmp_path):
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    base = staging / hashlib.sha256(b"alice").hexdigest()
    base.mkdir(parents=True)
    marker = base / "req-gone.complete"
    marker.write_text("")

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert written == set()
    assert not marker.exists()


def test_missing_user_staging_dir_returns_empty(tmp_path):
    written = sweep_sidecar_staging(
        staging_root=tmp_path / "staging", scratch_root=tmp_path / "scratch",
        user_id="alice", api_user="alice",
    )
    assert written == set()


def test_invalid_user_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        sweep_sidecar_staging(
            staging_root=tmp_path / "staging", scratch_root=tmp_path / "scratch",
            user_id="../evil", api_user="alice",
        )


def test_symlinks_are_skipped(tmp_path):
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-publish")
    base = _stage(staging, "alice", "req-3", {"ok.csv": "ok"})
    (base / "req-3" / "evil-link").symlink_to(secret)

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert written == {"nextseek-artifacts/ok.csv"}
    assert not (scratch / "alice" / "nextseek-artifacts" / "evil-link").exists()


# ----------------------------------------------- collision safety (T10R H-1)


def test_same_sweep_collision_disambiguates_instead_of_clobbering(tmp_path, caplog):
    """Two request dirs staging the same relative path in ONE sweep must both
    survive: the second lands as <stem>__1<suffix> (run_batch.py pattern)."""
    import logging

    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    base = _stage(staging, "alice", "req-1", {"report.xlsx": "first"})
    _stage(staging, "alice", "req-2", {"report.xlsx": "second"})
    _stage(staging, "alice", "req-3", {"report.xlsx": "third"})

    with caplog.at_level(logging.WARNING):
        written = sweep_sidecar_staging(
            staging_root=staging, scratch_root=scratch,
            user_id="alice", api_user="alice",
        )
    out = scratch / "alice" / "nextseek-artifacts"
    assert (out / "report.xlsx").read_text() == "first"
    assert (out / "report__1.xlsx").read_text() == "second"
    assert (out / "report__2.xlsx").read_text() == "third"
    assert written == {
        "nextseek-artifacts/report.xlsx",
        "nextseek-artifacts/report__1.xlsx",
        "nextseek-artifacts/report__2.xlsx",
    }
    # all staging dirs cleaned up
    for req in ("req-1", "req-2", "req-3"):
        assert not (base / req).exists()
        assert not (base / f"{req}.complete").exists()
    # a WARNING names the relative path (no file contents/values)
    warnings = [r.getMessage() for r in caplog.records
                if r.levelname == "WARNING"]
    assert any("nextseek-artifacts/report.xlsx" in m for m in warnings)
    assert all(
        "first" not in m and "second" not in m and "third" not in m
        for m in warnings
    )


def test_cross_sweep_collision_does_not_clobber_prior_turn(tmp_path):
    """A file already published in an earlier turn must not be overwritten by
    a later sweep staging the same relative path."""
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    prior = scratch / "alice" / "nextseek-artifacts" / "report.xlsx"
    prior.parent.mkdir(parents=True)
    prior.write_text("earlier-turn")
    _stage(staging, "alice", "req-9", {"report.xlsx": "later-turn"})

    written = sweep_sidecar_staging(
        staging_root=staging, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert prior.read_text() == "earlier-turn"  # untouched
    renamed = scratch / "alice" / "nextseek-artifacts" / "report__1.xlsx"
    assert renamed.read_text() == "later-turn"
    assert written == {"nextseek-artifacts/report__1.xlsx"}


# ----------------------------------- rmtree failure breadcrumb (T10R M-1)


def test_rmtree_failure_keeps_marker_for_retry(tmp_path, monkeypatch, caplog):
    """If post-copy cleanup fails, the marker must survive so the next sweep
    retries; the warning carries the exception TYPE only, never its message."""
    import logging

    from dmac_assistant import staging_sweep as mod

    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    base = _stage(staging, "alice", "req-stuck", {"report.xlsx": "data"})

    def failing_rmtree(path, *args, **kwargs):
        raise OSError("secret-detail-must-not-log")

    monkeypatch.setattr(mod.shutil, "rmtree", failing_rmtree)

    with caplog.at_level(logging.WARNING):
        written = sweep_sidecar_staging(
            staging_root=staging, scratch_root=scratch,
            user_id="alice", api_user="alice",
        )
    # files still copied + reported
    assert written == {"nextseek-artifacts/report.xlsx"}
    assert (scratch / "alice" / "nextseek-artifacts" / "report.xlsx").is_file()
    # marker kept as a re-sweep breadcrumb
    assert (base / "req-stuck.complete").exists()
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("OSError" in m for m in msgs)
    assert all("secret-detail-must-not-log" not in m for m in msgs)


def test_hash_parity_with_sidecar_staging_layout(tmp_path):
    """CARRY-FORWARD pin: stage a file via the REAL sidecar.app.staging helpers
    and assert sweep_sidecar_staging finds it — i.e. the sweep's sha256 lookup
    targets exactly the directory the sidecar's _user_hash writes to."""
    from sidecar.app import staging as sidecar_staging
    from sidecar.app.contract import NsLogin

    class _Cfg:
        def __init__(self, root):
            self.staging_dir = str(root)

    staging_root = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    src = tmp_path / "out"
    src.mkdir()
    (src / "report.xlsx").write_text("real-sidecar-staged")

    cfg = _Cfg(staging_root)
    login = NsLogin(api_user="alice", api_pass="p")
    stage = sidecar_staging.make_stage(cfg, login, request_id="req-real")
    stage("report", {"saved_files": {"xlsx": str(src / "report.xlsx")}})

    # belt-and-braces: the two hash functions agree on the directory name
    expected_dir = staging_root / sidecar_staging._user_hash("alice")
    assert expected_dir.is_dir()

    written = sweep_sidecar_staging(
        staging_root=staging_root, scratch_root=scratch,
        user_id="alice", api_user="alice",
    )
    assert written == {"nextseek-artifacts/report.xlsx"}
    dst = scratch / "alice" / "nextseek-artifacts" / "report.xlsx"
    assert dst.read_text() == "real-sidecar-staged"
    # swept request cleaned up in the sidecar's own layout
    assert not (expected_dir / "req-real").exists()
    assert not (expected_dir / "req-real.complete").exists()
