"""Plan A · T0: host pyproject.toml MUST stay at requires-python = '>=3.12'.

The 3.14 floor lives only inside the dmac-assistant image. The host bridge
process never imports chat_nextseek; bumping the host floor would break
local dev and CI on machines that only have Python 3.12 installed.

This is a regression-guard test: if a future task author edits pyproject.toml
to '>=3.14', this test fires immediately rather than waiting for a downstream
CI agent on Python 3.12 to fail with an opaque resolver error.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def test_host_pyproject_requires_python_is_312() -> None:
    """The host floor MUST stay at >=3.12; the 3.14 image floor is image-only."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12"' in text, (
        "Host pyproject.toml floor was bumped above >=3.12. Plan A T0 R4 "
        "decision: the 3.14 floor lives only inside the image. Revert the "
        "bump, or amend Plan A T0 explicitly."
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed on host")
def test_uv_lock_check_succeeds_on_host() -> None:
    """`uv lock --check` MUST succeed on the host (i.e., on host Python).

    If host pyproject is bumped to >=3.14 OR if `chat_nextseek` is added to
    the host deps without the image-only fallback, `uv lock --check` on a
    Python 3.12 host will fail. This test is the gate.
    """
    result = subprocess.run(
        ["uv", "lock", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"uv lock --check failed on host (rc={result.returncode}). "
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
        "Plan A T0 invariant: host uv sync MUST succeed on Python 3.12."
    )
