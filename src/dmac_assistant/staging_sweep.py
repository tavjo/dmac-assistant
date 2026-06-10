"""Sweep the sidecar's per-user staging dir into the user's scratch (OD-2, §10).

Maps the sidecar's hashed-user dir back to the bridge identity.user_id. Only sweeps
request dirs with a `.complete` marker (never partial). Returns the relative paths
copied so ws.py can union them into the post-turn `new_files` set (ordering, §10)."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def sweep_sidecar_staging(*, staging_root: Path, scratch_root: Path, user_id: str,
                          api_user: str) -> set[str]:
    """Copy completed staged artifacts for this user into scratch/<user_id>/.

    Returns the set of scratch-relative paths written (for new_files union)."""
    if not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"invalid user_id: {user_id!r}")
    # MUST match sidecar.app.staging._user_hash — pinned by the parity test in
    # tests/unit/test_staging_sweep.py (silent drift = artifacts never published).
    user_hash = hashlib.sha256(api_user.encode("utf-8")).hexdigest()
    src_base = staging_root / user_hash
    if not src_base.is_dir():
        return set()
    dst_base = scratch_root / user_id
    written: set[str] = set()
    for marker in sorted(src_base.glob("*.complete")):
        req_dir = src_base / marker.stem
        if not req_dir.is_dir():
            marker.unlink(missing_ok=True)
            continue
        for src in sorted(req_dir.rglob("*")):
            if src.is_symlink() or not src.is_file():
                continue
            rel = Path("nextseek-artifacts") / src.relative_to(req_dir)
            dst = dst_base / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.add(str(rel))
        # cleanup after a successful sweep (gate 12)
        shutil.rmtree(req_dir, ignore_errors=True)
        marker.unlink(missing_ok=True)
    return written
