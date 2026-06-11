"""Sweep the sidecar's per-user staging dir into the user's scratch (OD-2, §10).

Maps the sidecar's hashed-user dir back to the bridge identity.user_id. Only sweeps
request dirs with a `.complete` marker (never partial). Returns the relative paths
copied so ws.py can union them into the post-turn `new_files` set (ordering, §10)."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _disambiguate(dst: Path) -> Path:
    """First free `<stem>__N<suffix>` sibling (run_batch.py promotion pattern)."""
    n = 1
    candidate = dst.parent / f"{dst.stem}__{n}{dst.suffix}"
    while candidate.exists():
        n += 1
        candidate = dst.parent / f"{dst.stem}__{n}{dst.suffix}"
    return candidate


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
            if dst.exists():
                # never clobber a previously published artifact (same sweep or
                # an earlier turn) — rename with the repo's __N pattern.
                dst = _disambiguate(dst)
                # log only the relative path, never file contents/values
                log.warning(
                    "staging sweep: collision on %s, renamed to %s",
                    rel, dst.name,
                )
                rel = rel.parent / dst.name
            shutil.copy2(src, dst)
            written.add(str(rel))
        # cleanup after a successful sweep (gate 12); on failure keep the
        # marker as a breadcrumb so the next sweep retries the cleanup.
        try:
            shutil.rmtree(req_dir)
        except OSError as exc:
            # log only the exception TYPE — its message may echo paths/values
            log.warning(
                "staging sweep: cleanup of request dir failed (%s); "
                "keeping marker for retry", type(exc).__name__,
            )
            continue
        marker.unlink(missing_ok=True)
    return written
