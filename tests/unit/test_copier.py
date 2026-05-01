"""Plan A · T12: copy_files publishes a specific file list flat under user_id/."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def fixture_layout(tmp_path):
    scratch = tmp_path / "scratch"
    output = tmp_path / "output"
    (scratch / "alice").mkdir(parents=True)
    (output / "alice").mkdir(parents=True)
    return scratch, output


def test_publishes_listed_files(fixture_layout):
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    (scratch / "alice" / "a.json").write_text("v1")
    (scratch / "alice" / "nested").mkdir()
    (scratch / "alice" / "nested" / "b.txt").write_text("v2")

    copied = copy_files(scratch, output, "alice", {"a.json", "nested/b.txt"})

    assert (output / "alice" / "a.json").read_text() == "v1"
    assert (output / "alice" / "nested" / "b.txt").read_text() == "v2"
    assert set(copied) == {
        output / "alice" / "a.json",
        output / "alice" / "nested" / "b.txt",
    }


def test_copy_is_idempotent_and_overwrites_on_change(fixture_layout):
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    f = scratch / "alice" / "a.txt"
    f.write_text("v1")
    copy_files(scratch, output, "alice", {"a.txt"})
    f.write_text("v2")
    copy_files(scratch, output, "alice", {"a.txt"})
    assert (output / "alice" / "a.txt").read_text() == "v2"


def test_missing_source_skipped_silently(fixture_layout):
    """If a snapshotted file vanished between snapshot and copy (race),
    skip it rather than raise."""
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    copied = copy_files(scratch, output, "alice", {"ghost.json"})
    assert copied == []
    assert not (output / "alice" / "ghost.json").exists()


def test_user_id_validated(fixture_layout):
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    with pytest.raises(ValueError, match="invalid user_id"):
        copy_files(scratch, output, "../etc", {"a.txt"})


def test_skips_symlinks(fixture_layout):
    """M2 invariant: a path that resolves to a symlink at copy time MUST
    NOT be dereferenced. Defense against the agent staging /etc/passwd."""
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    target = scratch / "alice" / "real.txt"
    target.write_text("HOST SECRET")
    os.symlink(target, scratch / "alice" / "looks-innocent.txt")

    copied = copy_files(scratch, output, "alice", {"looks-innocent.txt"})
    assert copied == []
    assert not (output / "alice" / "looks-innocent.txt").exists()


def test_rejects_path_traversal(fixture_layout):
    """A relative path with `..` or absolute components MUST be refused
    even if the file exists. Defense against an adversarial run_tracker
    snapshot or a poisoned argument."""
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    copied = copy_files(scratch, output, "alice", {"../escape.txt", "/etc/passwd"})
    assert copied == []
    # Double-check no file was written anywhere outside the user output dir.
    assert not (output.parent / "escape.txt").exists()


def test_creates_output_user_dir_if_missing(fixture_layout, tmp_path):
    """If output/<user_id>/ does not exist (first turn ever), copy_files
    creates it rather than crashing."""
    from dmac_assistant.copier import copy_files
    scratch = tmp_path / "scratch2"
    output = tmp_path / "output2"
    (scratch / "bob").mkdir(parents=True)
    (scratch / "bob" / "first.txt").write_text("hi")
    copied = copy_files(scratch, output, "bob", {"first.txt"})
    assert copied == [output / "bob" / "first.txt"]


def test_sorted_iteration_for_determinism(fixture_layout):
    """Returned list must be sorted lexicographically by destination path —
    callers (and the dispatch wrapper) rely on deterministic order."""
    from dmac_assistant.copier import copy_files
    scratch, output = fixture_layout
    for n in ("c.txt", "a.txt", "b.txt"):
        (scratch / "alice" / n).write_text("x")
    copied = copy_files(scratch, output, "alice", {"a.txt", "b.txt", "c.txt"})
    assert [p.name for p in copied] == ["a.txt", "b.txt", "c.txt"]
