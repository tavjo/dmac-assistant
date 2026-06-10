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
