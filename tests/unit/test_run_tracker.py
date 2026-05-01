"""Plan A · T12: scratch-file diff discovers per-turn artifacts."""
from __future__ import annotations

import pytest


def test_snapshot_returns_relpath_to_size_mtime(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_files
    scratch = tmp_path / "scratch"
    user = scratch / "alice"
    user.mkdir(parents=True)
    (user / "a.json").write_text("123")
    (user / "nested").mkdir()
    (user / "nested" / "b.txt").write_text("hello")

    snap = snapshot_scratch_files(scratch, "alice")
    assert set(snap.keys()) == {"a.json", "nested/b.txt"}
    for key, (size, mtime_ns) in snap.items():
        assert isinstance(size, int) and size > 0
        assert isinstance(mtime_ns, int) and mtime_ns > 0


def test_diff_returns_new_and_changed_files(tmp_path):
    from dmac_assistant.run_tracker import diff_files
    before = {"a.json": (3, 1000), "b.txt": (5, 2000)}
    after = {
        "a.json": (3, 1000),       # unchanged
        "b.txt": (5, 2500),         # mtime changed -> include
        "c.json": (10, 3000),       # new -> include
    }
    assert diff_files(before, after) == {"b.txt", "c.json"}


def test_diff_changed_size_only(tmp_path):
    from dmac_assistant.run_tracker import diff_files
    before = {"a.json": (3, 1000)}
    after = {"a.json": (4, 1000)}  # mtime same, size changed
    assert diff_files(before, after) == {"a.json"}


def test_snapshot_missing_user_dir_is_empty(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_files
    assert snapshot_scratch_files(tmp_path / "ghost", "alice") == {}


def test_snapshot_skips_symlinks(tmp_path):
    """Defense-in-depth: even though copy_files re-checks, the snapshot
    must not stat through a symlink (could pin host secrets via mtime
    side-channel). A symlink is excluded from the file set entirely."""
    import os
    from dmac_assistant.run_tracker import snapshot_scratch_files
    scratch = tmp_path / "scratch"
    user = scratch / "alice"
    user.mkdir(parents=True)
    (user / "real.txt").write_text("ok")
    target = tmp_path / "secret.txt"
    target.write_text("HOST SECRET")
    os.symlink(target, user / "evil.txt")
    snap = snapshot_scratch_files(scratch, "alice")
    assert "real.txt" in snap
    assert "evil.txt" not in snap


def test_user_id_validated(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_files
    with pytest.raises(ValueError, match="invalid user_id"):
        snapshot_scratch_files(tmp_path, "../etc")
