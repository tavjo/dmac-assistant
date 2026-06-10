"""T10 (OD-2, §10 — ordering is load-bearing): `_sweep_then_diff` must sweep the
sidecar staging dir BEFORE the post-turn scratch snapshot, and union swept paths
into `new`, so a swept-only file with an unchanged mtime is still published the
same turn."""
import logging
from types import SimpleNamespace

import dmac_assistant.staging_sweep as staging_sweep_mod
import dmac_assistant.ws as ws


def _config(tmp_path, *, staging_root):
    return SimpleNamespace(
        scratch_root=tmp_path / "scratch",
        sidecar_staging_root=staging_root,
    )


def _identity():
    return SimpleNamespace(user_id="alice")


def test_sweep_runs_before_snapshot_and_unions_paths(tmp_path, monkeypatch):
    calls: list[str] = []
    pre = {"old.txt": 1.0}
    after_snapshot = {"old.txt": 1.0}  # diff alone would be EMPTY

    def fake_sweep(*, staging_root, scratch_root, user_id, api_user):
        calls.append("sweep")
        assert staging_root == tmp_path / "staging"
        assert scratch_root == tmp_path / "scratch"
        assert user_id == "alice"
        assert api_user == "alice"  # bridge user_id == NS api_user
        return {"nextseek-artifacts/report.xlsx"}

    def fake_snapshot(scratch_root, user_id):
        calls.append("snapshot")
        return after_snapshot

    monkeypatch.setattr(staging_sweep_mod, "sweep_sidecar_staging", fake_sweep)
    monkeypatch.setattr(ws, "snapshot_scratch_files", fake_snapshot)

    config = _config(tmp_path, staging_root=tmp_path / "staging")
    after, new = ws._sweep_then_diff(config, _identity(), pre)

    assert calls == ["sweep", "snapshot"], "sweep MUST run before the snapshot (§10)"
    assert after is after_snapshot
    # swept-only file with an unchanged scratch diff still appears in `new`
    assert new == {"nextseek-artifacts/report.xlsx"}


def test_no_sweep_when_staging_root_unset(tmp_path, monkeypatch):
    def boom(**_kwargs):
        raise AssertionError("sweep must not be called when staging root is None")

    monkeypatch.setattr(staging_sweep_mod, "sweep_sidecar_staging", boom)
    monkeypatch.setattr(ws, "snapshot_scratch_files", lambda root, uid: {"a": 1.0})

    config = _config(tmp_path, staging_root=None)
    after, new = ws._sweep_then_diff(config, _identity(), {})
    assert after == {"a": 1.0}
    assert new == {"a"}


def test_sweep_failure_does_not_kill_the_turn(tmp_path, monkeypatch, caplog):
    def failing_sweep(**_kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(staging_sweep_mod, "sweep_sidecar_staging", failing_sweep)
    monkeypatch.setattr(
        ws, "snapshot_scratch_files", lambda root, uid: {"fresh.txt": 2.0}
    )

    config = _config(tmp_path, staging_root=tmp_path / "staging")
    with caplog.at_level(logging.WARNING, logger="dmac_assistant.ws"):
        after, new = ws._sweep_then_diff(config, _identity(), {})
    assert new == {"fresh.txt"}  # the ordinary diff still publishes
    assert any("staging sweep failed" in r.message for r in caplog.records)
    # R-03: only the exception TYPE is logged, never its message/values
    assert all("disk on fire" not in r.getMessage() for r in caplog.records)
