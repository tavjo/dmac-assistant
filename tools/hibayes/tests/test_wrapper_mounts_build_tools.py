"""tools/hibayes/tests/test_wrapper_mounts_build_tools.py — task-3R2 regression.

Pins that the three in-image HiBayes-eval wrapper scripts bind-mount the
`build_tools/` sibling project and expose it on PYTHONPATH, so that
`tests/conftest.py`'s module-level `from build_tools.verify_env import ...`
resolves when pytest collects in-image. Without these, the Section 8 in-image
`pytest` commands abort at conftest collection (pytest exit 2).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPERS = [
    REPO_ROOT / "scripts" / "run_hibayes_eval_artifact.sh",
    REPO_ROOT / "scripts" / "run_hibayes_eval_functional.sh",
    REPO_ROOT / "scripts" / "run_hibayes_eval.sh",
]


@pytest.mark.parametrize("wrapper", WRAPPERS, ids=lambda p: p.name)
def test_wrapper_mounts_build_tools_readonly(wrapper: Path) -> None:
    content = wrapper.read_text(encoding="utf-8")
    assert "build_tools" in content, (
        f"{wrapper.name} must bind-mount build_tools/ — tests/conftest.py:11 "
        f"hard-imports build_tools.verify_env at collection time."
    )
    # Mount must be read-only.
    assert "/build_tools:" in content and ":ro" in content, (
        f"{wrapper.name}: build_tools/ mount must target a container path "
        f"and be read-only (:ro)."
    )


@pytest.mark.parametrize("wrapper", WRAPPERS, ids=lambda p: p.name)
def test_wrapper_pythonpath_covers_build_tools_root(wrapper: Path) -> None:
    """build_tools is mounted at /work/build_tools; PYTHONPATH must include
    the directory that makes `import build_tools` resolve (i.e. /work)."""
    content = wrapper.read_text(encoding="utf-8")
    # PYTHONPATH must include /work (the parent of /work/build_tools) in
    # addition to /work/src. Accept either order.
    assert "PYTHONPATH=" in content
    pythonpath_lines = [ln for ln in content.splitlines() if "PYTHONPATH=" in ln]
    assert pythonpath_lines, f"{wrapper.name}: no PYTHONPATH= line"
    joined = " ".join(pythonpath_lines)
    assert "/work/src" in joined and ("/work:" in joined or joined.rstrip().endswith("/work")), (
        f"{wrapper.name}: PYTHONPATH must cover both /work/src and /work so "
        f"`import build_tools` resolves; got: {pythonpath_lines!r}"
    )
