"""Plan A · T4: scratch -> output copier."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def fixture_layout(tmp_path):
    scratch = tmp_path / "scratch" / "alice"
    output = tmp_path / "output" / "alice"
    scratch.mkdir(parents=True)
    output.mkdir(parents=True)
    return scratch, output


def test_publishes_files(fixture_layout):
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    run_dir = scratch / "260427_120000_alice"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps({"ok": True}))

    copied = copy_run_artifacts(scratch.parent, output.parent, "alice", "260427_120000_alice")
    assert (output / "260427_120000_alice" / "report.json").read_text() == json.dumps({"ok": True})
    assert copied == [output / "260427_120000_alice" / "report.json"]


def test_idempotent(fixture_layout):
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    (scratch / "run-x").mkdir()
    (scratch / "run-x" / "a.txt").write_text("v1")
    copy_run_artifacts(scratch.parent, output.parent, "alice", "run-x")
    (scratch / "run-x" / "a.txt").write_text("v2")
    copy_run_artifacts(scratch.parent, output.parent, "alice", "run-x")
    assert (output / "run-x" / "a.txt").read_text() == "v2"


def test_missing_source_noop(fixture_layout):
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    assert copy_run_artifacts(scratch.parent, output.parent, "alice", "ghost") == []
    assert not (output / "ghost").exists()


def test_user_id_validated(fixture_layout):
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    with pytest.raises(ValueError, match="invalid user_id"):
        copy_run_artifacts(scratch.parent, output.parent, "../etc", "run")


def test_run_id_validated(fixture_layout):
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    with pytest.raises(ValueError, match="invalid run_id"):
        copy_run_artifacts(scratch.parent, output.parent, "alice", "../escape")


def test_skips_symlinks(fixture_layout):
    """M2: symlinks in scratch must not be dereferenced — defends against
    in-container agent staging /etc/passwd as a 'tool output'."""
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    run_dir = scratch / "evil-run"
    run_dir.mkdir()
    target = scratch / "real-secret.txt"
    target.write_text("HOST SECRET")
    os.symlink(target, run_dir / "looks-innocent.txt")

    copied = copy_run_artifacts(scratch.parent, output.parent, "alice", "evil-run")
    assert copied == []
    assert not (output / "evil-run" / "looks-innocent.txt").exists()


def test_skips_symlink_to_directory(fixture_layout, tmp_path):
    """M2 (R2): symlinks to *directories* must not be descended into — closes
    the os.walk-vs-rglob attack vector where rglob would follow directory
    symlinks and exfiltrate the linked tree's contents."""
    from dmac_assistant.copier import copy_run_artifacts
    scratch, output = fixture_layout
    run_dir = scratch / "evil-dir-run"
    run_dir.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    (private / "secret.txt").write_text("PRIVATE HOST SECRET")
    os.symlink(private, run_dir / "exfil")

    copy_run_artifacts(scratch.parent, output.parent, "alice", "evil-dir-run")

    # The symlinked directory must not be descended into AND the symlink
    # itself must not be created in dst.
    assert not (output / "evil-dir-run" / "exfil" / "secret.txt").exists()
    assert not (output / "evil-dir-run" / "exfil").exists()
