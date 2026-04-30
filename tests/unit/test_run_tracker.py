"""Plan A · T5: scratch-listing diff discovers run_ids per turn."""
from __future__ import annotations

import pytest


def test_snapshot_returns_subdir_names(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_runs
    scratch = tmp_path / "scratch"
    (scratch / "alice").mkdir(parents=True)
    (scratch / "alice" / "260427_120000_alice").mkdir()
    (scratch / "alice" / "260427_120100_alice").mkdir()
    snap = snapshot_scratch_runs(scratch, "alice")
    assert snap == {"260427_120000_alice", "260427_120100_alice"}


def test_diff_returns_only_new(tmp_path):
    from dmac_assistant.run_tracker import diff_runs
    before = {"a", "b"}
    after = {"a", "b", "c", "d"}
    assert diff_runs(before, after) == {"c", "d"}


def test_snapshot_missing_user_dir_is_empty(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_runs
    snap = snapshot_scratch_runs(tmp_path / "ghost", "alice")
    assert snap == set()


def test_user_id_validated(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_runs
    with pytest.raises(ValueError, match="invalid user_id"):
        snapshot_scratch_runs(tmp_path, "../etc")


def test_snapshot_ignores_files(tmp_path):
    from dmac_assistant.run_tracker import snapshot_scratch_runs
    scratch = tmp_path / "scratch"
    (scratch / "alice").mkdir(parents=True)
    (scratch / "alice" / "directly-a-file.txt").write_text("nope")
    (scratch / "alice" / "real-run-dir").mkdir()
    assert snapshot_scratch_runs(scratch, "alice") == {"real-run-dir"}
