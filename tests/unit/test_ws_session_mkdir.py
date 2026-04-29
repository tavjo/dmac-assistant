"""Plan A · T3: per-user output dir is created at session start.

H3: missing dir would cause Docker bind error on first login."""
from __future__ import annotations

from pathlib import Path

from dmac_assistant.ws import ensure_user_output_dir


def test_ensure_user_output_dir_creates_missing(tmp_path):
    output_root = tmp_path / "output"
    # output_root and per-user subdir do not exist yet.
    ensure_user_output_dir(output_root, "alice")
    assert (output_root / "alice").is_dir()


def test_ensure_user_output_dir_idempotent(tmp_path):
    output_root = tmp_path / "output"
    (output_root / "alice").mkdir(parents=True)
    # Should not raise.
    ensure_user_output_dir(output_root, "alice")
    assert (output_root / "alice").is_dir()


def test_ensure_user_output_dir_rejects_traversal(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="invalid user_id"):
        ensure_user_output_dir(tmp_path, "../escape")
