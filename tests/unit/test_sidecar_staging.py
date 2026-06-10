import hashlib
from pathlib import Path
import pytest
from sidecar.app import staging
from sidecar.app.contract import NsLogin


class _Cfg:
    def __init__(self, root):
        self.staging_dir = str(root)


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
