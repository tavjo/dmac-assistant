"""tools/hibayes/tests/test_in_image_cov_invocation.py — task-3R3 regression.

Pins that the T3.1 / T3.2 Section 8 in-image coverage commands neutralize the
global pyproject addopts and use a dedicated coverage config that does NOT omit
src/dmac_assistant/eval/*. Without this, the in-image --cov gate measures the
wrong scope (addopts leak) and zeroes the axis module (omit list).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_SPECS = [
    REPO_ROOT / ".claude" / "tasks" / "task-10-in-image-artifact-axis.md",
    REPO_ROOT / ".claude" / "tasks" / "task-11-in-image-functional-axis.md",
]
COV_CONFIG = REPO_ROOT / "tools" / "hibayes" / "in_image_coverage.cfg"


@pytest.mark.parametrize("spec", TASK_SPECS, ids=lambda p: p.name)
def test_section8_in_image_cov_neutralizes_addopts(spec: Path) -> None:
    text = spec.read_text(encoding="utf-8")
    assert '--override-ini="addopts="' in text, (
        f"{spec.name} Section 8 in-image pytest command must pass "
        f'--override-ini="addopts=" — otherwise the global pyproject addopts '
        f"injects --cov=src/dmac_assistant + a second --cov-fail-under."
    )
    assert "--cov-config=tools/hibayes/in_image_coverage.cfg" in text, (
        f"{spec.name} Section 8 must point --cov-config at the in-image "
        f"coverage config so the global omit does not zero the axis tree."
    )


def test_in_image_coverage_config_exists_and_does_not_omit_axis_tree() -> None:
    assert COV_CONFIG.is_file(), "tools/hibayes/in_image_coverage.cfg missing"
    content = COV_CONFIG.read_text(encoding="utf-8")
    assert "src/dmac_assistant/eval" not in content, (
        "in_image_coverage.cfg must NOT omit src/dmac_assistant/eval/* — the "
        "in-image gate exists precisely to measure that tree."
    )


def test_global_pyproject_still_omits_axis_tree_for_host_gate() -> None:
    """DD-13: the HOST gate MUST still omit src/dmac_assistant/eval/*. This
    remediation must not regress the host-omit."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"src/dmac_assistant/eval/*"' in pyproject, (
        "pyproject.toml [tool.coverage.run].omit must keep "
        '"src/dmac_assistant/eval/*" for the host coverage gate (DD-13).'
    )
