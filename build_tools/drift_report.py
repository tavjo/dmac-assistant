"""Render a drift summary for `make image-preflight`."""
from __future__ import annotations

import subprocess
from pathlib import Path

_DIFF_PATHS = ("container/CLAUDE.md", "docs/nextseek/")
_UNAVAILABLE = "(git diff unavailable - not a git checkout or git not on PATH)"


def format_drift_summary(repo_root: Path) -> str:
    """Return `git diff --stat` output for the freshness-gate surface."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--stat", "--", *_DIFF_PATHS],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return _UNAVAILABLE

    if result.returncode != 0:
        return _UNAVAILABLE
    return result.stdout

