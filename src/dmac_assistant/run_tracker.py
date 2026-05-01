"""Pre/post-turn snapshotter for the scratch directory.

The bridge does NOT have a per-turn run_id concept exposed by Claude or
the plugin. Instead, it observes the filesystem: snapshot subdir names
in /<scratch_root>/<user_id>/ before the turn, snapshot again after,
and the new entries are the run_ids the copier should publish.

Resolves adversarial CRITICAL-1 (D26).
"""
from __future__ import annotations

import re
from pathlib import Path

_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def snapshot_scratch_runs(scratch_root: Path, user_id: str) -> set[str]:
    """Return the set of subdirectory names under <scratch_root>/<user_id>/.

    Returns empty set if the user dir does not exist (first-turn case).
    Files are excluded — only directories.
    """
    if not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"invalid user_id: {user_id!r}")
    user_dir = scratch_root / user_id
    if not user_dir.is_dir():
        return set()
    return {p.name for p in user_dir.iterdir() if p.is_dir()}


def diff_runs(before: set[str], after: set[str]) -> set[str]:
    """Return run_ids present in `after` but not in `before`."""
    return after - before
