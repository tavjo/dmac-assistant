"""Bridge-side copier: scratch/<run-id>/ -> output/<run-id>/.

Runs after every container turn. Reads from the rw scratch volume on the
host, writes to the rw-on-host / ro-in-container output volume. CC never
touches the output dir directly. Symlinks are skipped — defense against
the in-container agent staging host paths as 'tool outputs' (M2).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def copy_run_artifacts(
    scratch_root: Path,
    output_root: Path,
    user_id: str,
    run_id: str,
) -> list[Path]:
    """Copy /scratch_root/<user_id>/<run_id>/ to /output_root/<user_id>/<run_id>/.

    Returns destination paths written. Idempotent. No-op if source is missing.
    Skips symlinks (M2). Validates user_id and run_id against anchored regex.
    """
    if not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"invalid user_id: {user_id!r}")
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")

    src = scratch_root / user_id / run_id
    if not src.is_dir():
        return []

    dst = output_root / user_id / run_id
    dst.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    # os.walk(..., followlinks=False) refuses to descend into symlinked
    # directories. Combined with the per-entry is_symlink() skip below,
    # this closes the M2 symlink-to-directory exfiltration vector that
    # rglob("*") would otherwise enable (rglob follows directory symlinks
    # by default).
    for dirpath, _dirnames, filenames in sorted(os.walk(src, followlinks=False)):
        for filename in sorted(filenames):
            src_path = Path(dirpath) / filename
            if src_path.is_symlink():
                log.warning("copier: skipping symlink %s", src_path)
                continue
            if not src_path.is_file():
                continue
            rel = src_path.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, target)
            written.append(target)
    return written
