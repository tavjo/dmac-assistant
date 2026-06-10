"""Per-user artifact staging (§10, OD-2, U-7). Never mounts scratch; writes to a
host-bind staging dir the bridge sweeps. Hashed user key (never raw api_user as a
path segment). Atomic publish via a sibling `<request>.complete` marker the bridge
waits on. The bridge maps the hashed dir back to identity.user_id (T10)."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable

from sidecar.app.contract import NsLogin


class StagingError(RuntimeError):
    """→ STAGING_ERROR / exit 9."""


def _user_hash(api_user: str) -> str:
    return hashlib.sha256(api_user.encode("utf-8")).hexdigest()


def make_stage(cfg: Any, login: NsLogin, request_id: str) -> Callable[[str, dict], dict]:
    """Return stage(op, result) that copies result['saved_files'] into staging and
    writes a completion marker, returning result augmented with 'staged_files'."""
    base = Path(cfg.staging_dir) / _user_hash(login.api_user)
    req_dir = base / request_id
    marker = base / f"{request_id}.complete"

    def stage(op: str, result: dict) -> dict:
        saved = result.get("saved_files") or {}
        if not saved:
            return result  # no artifacts to stage (e.g. empty report)
        try:
            req_dir.mkdir(parents=True, exist_ok=True)
            staged: list[str] = []
            for _key, src_path in saved.items():
                src = Path(src_path)
                if not src.is_file():
                    raise StagingError(f"saved artifact missing: {src_path}")
                dst = req_dir / src.name
                shutil.copy2(src, dst)
                staged.append(str(dst))
            marker.write_text("")  # atomic-enough: only written after all copies succeed
        except StagingError:
            raise
        except OSError as exc:
            raise StagingError(f"staging failed: {type(exc).__name__}") from exc
        out = dict(result)
        out["staged_files"] = staged
        return out

    return stage


def cleanup_request(cfg: Any, api_user: str, request_id: str) -> None:
    """Remove a request's staged dir + marker. Called by the bridge after sweep (T10)
    or by a periodic janitor for abandoned dirs."""
    base = Path(cfg.staging_dir) / _user_hash(api_user)
    shutil.rmtree(base / request_id, ignore_errors=True)
    (base / f"{request_id}.complete").unlink(missing_ok=True)
