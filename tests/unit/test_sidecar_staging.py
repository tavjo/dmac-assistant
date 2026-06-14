"""Staging tests (T16 extended): make_stage (path-copy) + make_stage_bytes (bytes writer).
make_stage_bytes returns a (stage_bytes, commit) pair; the .complete marker is written
by commit() once after all artifacts are staged — never inside the per-artifact loop.
"""
import hashlib
from pathlib import Path
import pytest
from sidecar.app import staging
from sidecar.app.contract import NsLogin


class _Cfg:
    def __init__(self, root):
        self.staging_dir = str(root)


# ---- make_stage (path-copy entry point, unchanged from T7) -------------------

def test_stage_copies_saved_files_into_per_user_request_dir(tmp_path):
    src = tmp_path / "out"
    src.mkdir()
    (src / "report.xlsx").write_text("x")
    (src / "report.html").write_text("<html>")
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-1")
    out = stage("report", {"summary": "s", "saved_files": {"xlsx": str(src / "report.xlsx"),
                                                            "html": str(src / "report.html")}, "rows": []})
    user_hash = hashlib.sha256(b"alice").hexdigest()
    staged_dir = Path(cfg.staging_dir) / user_hash / "req-1"
    assert (staged_dir / "report.xlsx").exists() and (staged_dir / "report.html").exists()
    # completion marker present => bridge may sweep
    assert (Path(cfg.staging_dir) / user_hash / "req-1.complete").exists()
    # staged paths surfaced back in the result
    assert any("report.xlsx" in p for p in out["staged_files"])


def test_partial_not_marked_until_complete(tmp_path, monkeypatch):
    # If copy raises mid-way, no .complete marker is written.
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="bob", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-2")
    with pytest.raises(staging.StagingError):
        stage("report", {"saved_files": {"x": "/does/not/exist.xlsx"}})
    user_hash = hashlib.sha256(b"bob").hexdigest()
    assert not (Path(cfg.staging_dir) / user_hash / "req-2.complete").exists()


def test_cleanup_removes_completed_and_old_abandoned(tmp_path):
    cfg = _Cfg(tmp_path / "staging")
    user_hash = hashlib.sha256(b"alice").hexdigest()
    d = Path(cfg.staging_dir) / user_hash / "old"
    d.mkdir(parents=True)
    (d.parent / "old.complete").write_text("")
    staging.cleanup_request(cfg, "alice", "old")
    assert not d.exists() and not (d.parent / "old.complete").exists()


def test_empty_saved_files_returns_result_unchanged(tmp_path):
    """Empty/missing saved_files: no staging dir created, no marker, result returned as-is."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="charlie", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-3")
    result = {"summary": "done", "saved_files": {}}
    out = stage("report", result)
    user_hash = hashlib.sha256(b"charlie").hexdigest()
    assert not (Path(cfg.staging_dir) / user_hash / "req-3").exists()
    assert not (Path(cfg.staging_dir) / user_hash / "req-3.complete").exists()
    assert out == result


def test_no_saved_files_key_returns_result_unchanged(tmp_path):
    """Result dict with no 'saved_files' key at all: no staging, result passed through."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="dave", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-4")
    result = {"summary": "done"}
    out = stage("report", result)
    assert "staged_files" not in out
    assert out == result


def test_oserror_wrapped_as_staging_error(tmp_path, monkeypatch):
    """An OSError during shutil.copy2 (not from a missing file) is wrapped into StagingError."""
    import shutil
    src = tmp_path / "out"
    src.mkdir()
    (src / "report.xlsx").write_text("x")
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="eve", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-5")

    def _bad_copy(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", _bad_copy)
    with pytest.raises(staging.StagingError, match="staging failed"):
        stage("report", {"saved_files": {"xlsx": str(src / "report.xlsx")}})
    user_hash = hashlib.sha256(b"eve").hexdigest()
    assert not (Path(cfg.staging_dir) / user_hash / "req-5.complete").exists()


def test_api_user_never_in_staged_path(tmp_path):
    """Raw api_user must never appear as a path segment."""
    src = tmp_path / "out"
    src.mkdir()
    (src / "f.csv").write_text("a,b")
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="frank", api_pass="p")
    stage = staging.make_stage(cfg, login, request_id="req-6")
    out = stage("report", {"saved_files": {"csv": str(src / "f.csv")}})
    for p in out["staged_files"]:
        assert "frank" not in p


def test_cleanup_is_idempotent_when_dir_absent(tmp_path):
    """cleanup_request on an already-removed dir must not raise."""
    cfg = _Cfg(tmp_path / "staging")
    staging.cleanup_request(cfg, "grace", "nonexistent")  # must not raise


# ---- make_stage_bytes (T16 addition) ----------------------------------------

def test_make_stage_bytes_returns_callable_pair(tmp_path):
    """make_stage_bytes returns a (stage_bytes, commit) pair of callables."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    writer, committer = staging.make_stage_bytes(cfg, login, request_id="req-sb-1")
    assert callable(writer)
    assert callable(committer)


def test_stage_bytes_writes_bytes_to_staging_dir(tmp_path):
    """stage_bytes writes the given bytes to the per-user hashed staging dir."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    writer, _ = staging.make_stage_bytes(cfg, login, request_id="req-sb-2")
    staged_path = writer("report", "published_report", b"\x89PNG artifact")
    assert Path(staged_path).read_bytes() == b"\x89PNG artifact"
    user_hash = hashlib.sha256(b"alice").hexdigest()
    assert user_hash in staged_path
    assert "req-sb-2" in staged_path


def test_stage_bytes_does_not_write_complete_marker(tmp_path):
    """stage_bytes must NOT write the .complete marker (that's commit()'s job — F-T16-2-B)."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    writer, _ = staging.make_stage_bytes(cfg, login, request_id="req-sb-3")
    writer("report", "key1", b"data")
    user_hash = hashlib.sha256(b"alice").hexdigest()
    marker = Path(cfg.staging_dir) / user_hash / "req-sb-3.complete"
    assert not marker.exists()


def test_commit_writes_complete_marker(tmp_path):
    """commit() writes the .complete marker exactly once."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    writer, committer = staging.make_stage_bytes(cfg, login, request_id="req-sb-4")
    writer("report", "key1", b"data1")  # stage an artifact first
    user_hash = hashlib.sha256(b"alice").hexdigest()
    marker = Path(cfg.staging_dir) / user_hash / "req-sb-4.complete"
    assert not marker.exists()
    committer()
    assert marker.exists()


def test_commit_after_multi_artifact_loop(tmp_path):
    """commit() called once after staging multiple artifacts (F-T16-2-B pattern)."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="alice", api_pass="p")
    writer, committer = staging.make_stage_bytes(cfg, login, request_id="req-sb-5")
    artifacts = [("key1", b"bytes1"), ("key2", b"bytes2"), ("key3", b"bytes3")]
    paths = []
    for key, data in artifacts:
        paths.append(writer("report", key, data))
    committer()  # exactly once after the loop
    user_hash = hashlib.sha256(b"alice").hexdigest()
    marker = Path(cfg.staging_dir) / user_hash / "req-sb-5.complete"
    assert marker.exists()
    for path in paths:
        assert Path(path).exists()


def test_stage_bytes_api_user_never_in_path(tmp_path):
    """Raw api_user must never appear in the staged path (security invariant)."""
    cfg = _Cfg(tmp_path / "staging")
    login = NsLogin(api_user="frank", api_pass="p")
    writer, _ = staging.make_stage_bytes(cfg, login, request_id="req-sb-6")
    staged_path = writer("report", "artifact", b"data")
    assert "frank" not in staged_path


def test_stage_bytes_distinct_users_distinct_dirs(tmp_path):
    """Different users get different staging dirs (hashed by api_user)."""
    cfg = _Cfg(tmp_path / "staging")
    login_a = NsLogin(api_user="alice", api_pass="p")
    login_b = NsLogin(api_user="bob", api_pass="p")
    writer_a, _ = staging.make_stage_bytes(cfg, login_a, request_id="req-sb-7")
    writer_b, _ = staging.make_stage_bytes(cfg, login_b, request_id="req-sb-7")
    path_a = writer_a("report", "key", b"alice data")
    path_b = writer_b("report", "key", b"bob data")
    assert path_a != path_b
    assert Path(path_a).read_bytes() == b"alice data"
    assert Path(path_b).read_bytes() == b"bob data"
