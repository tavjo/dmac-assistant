"""tools/hibayes/tests/test_sibling_wrappers.py — flag-literal + syntax tests for T0.4.

Per locked DD-21 wrapper-script axis-awareness constraint + DD-28 per-axis layout +
plan-DD-01 sibling-scripts choice + DL-016 path-name correction + DL-017 verification
scoping (Wave-0 = syntax + literal-flag assertions; runtime smoke deferred to T3.1/T3.2).

The two new wrappers MUST bind-mount the new axes' own `config/` and `report_template/`
directories at `/work/config` and `/work/templates` (preserving the canonical container-side
mount targets). They MUST NOT reference `hibayes_runtime_reliability/` (the existing axis).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_WRAPPER = REPO_ROOT / "scripts" / "run_hibayes_eval_artifact.sh"
FUNCTIONAL_WRAPPER = REPO_ROOT / "scripts" / "run_hibayes_eval_functional.sh"


def test_artifact_wrapper_exists() -> None:
    assert ARTIFACT_WRAPPER.is_file()


def test_functional_wrapper_exists() -> None:
    assert FUNCTIONAL_WRAPPER.is_file()


def test_artifact_wrapper_is_executable() -> None:
    import os

    assert os.access(ARTIFACT_WRAPPER, os.X_OK), (
        f"{ARTIFACT_WRAPPER} must have execute bit set (chmod +x)"
    )


def test_functional_wrapper_is_executable() -> None:
    import os

    assert os.access(FUNCTIONAL_WRAPPER, os.X_OK), (
        f"{FUNCTIONAL_WRAPPER} must have execute bit set (chmod +x)"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_artifact_wrapper_passes_syntax_check() -> None:
    """DL-017: Wave-0 verification = `bash -n` syntax check."""
    result = subprocess.run(
        ["bash", "-n", str(ARTIFACT_WRAPPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n failed for {ARTIFACT_WRAPPER}:\n{result.stderr}"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_functional_wrapper_passes_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(FUNCTIONAL_WRAPPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n failed for {FUNCTIONAL_WRAPPER}:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Literal flag assertions (DL-016 path-name correction + DL-017 verification scoping)
# -----------------------------------------------------------------------------

def test_artifact_wrapper_mounts_artifact_axis_config() -> None:
    """Locked DD-28 new-axis layout: config/ source directory; /work/config target."""
    content = ARTIFACT_WRAPPER.read_text(encoding="utf-8")
    # The -v flag must point at the artifact axis's config/ directory.
    assert "src/dmac_assistant/eval/hibayes_artifact_validity/config" in content
    # Container-side target preserved (locked DD-21 canonical mount-point convention).
    assert "/work/config:ro" in content


def test_artifact_wrapper_mounts_artifact_axis_report_template() -> None:
    """Locked DD-28: report_template/ source (NOT templates/); /work/templates target."""
    content = ARTIFACT_WRAPPER.read_text(encoding="utf-8")
    assert "src/dmac_assistant/eval/hibayes_artifact_validity/report_template" in content
    assert "/work/templates:ro" in content


def test_functional_wrapper_mounts_functional_axis_config() -> None:
    content = FUNCTIONAL_WRAPPER.read_text(encoding="utf-8")
    assert "src/dmac_assistant/eval/hibayes_functional_usefulness/config" in content
    assert "/work/config:ro" in content


def test_functional_wrapper_mounts_functional_axis_report_template() -> None:
    content = FUNCTIONAL_WRAPPER.read_text(encoding="utf-8")
    assert (
        "src/dmac_assistant/eval/hibayes_functional_usefulness/report_template" in content
    )
    assert "/work/templates:ro" in content


# -----------------------------------------------------------------------------
# Anti-regression: wrappers MUST NOT mount the runtime-reliability axis directories
# -----------------------------------------------------------------------------

def test_artifact_wrapper_does_not_reference_runtime_reliability() -> None:
    """Locked DD-21 R32: artifact wrapper MUST NOT bind-mount runtime axis directories."""
    content = ARTIFACT_WRAPPER.read_text(encoding="utf-8")
    assert "hibayes_runtime_reliability/config" not in content
    assert "hibayes_runtime_reliability/templates" not in content
    assert "hibayes_runtime_reliability/report_template" not in content


def test_functional_wrapper_does_not_reference_runtime_reliability() -> None:
    content = FUNCTIONAL_WRAPPER.read_text(encoding="utf-8")
    assert "hibayes_runtime_reliability/config" not in content
    assert "hibayes_runtime_reliability/templates" not in content
    assert "hibayes_runtime_reliability/report_template" not in content


# -----------------------------------------------------------------------------
# PYTHONPATH preservation (R-08 from runtime axis; matches existing wrapper)
# -----------------------------------------------------------------------------

def test_artifact_wrapper_preserves_pythonpath_work_src() -> None:
    """`-e PYTHONPATH=/work/src` is REQUIRED — runtime entry points need it.

    See `scripts/run_hibayes_eval.sh:25-34` for the canonical comment block explaining why.
    """
    content = ARTIFACT_WRAPPER.read_text(encoding="utf-8")
    assert "PYTHONPATH=/work/src" in content


def test_functional_wrapper_preserves_pythonpath_work_src() -> None:
    content = FUNCTIONAL_WRAPPER.read_text(encoding="utf-8")
    assert "PYTHONPATH=/work/src" in content


# -----------------------------------------------------------------------------
# Existing runtime wrapper is untouched (regression guard)
# -----------------------------------------------------------------------------

def test_existing_runtime_wrapper_still_mounts_runtime_axis() -> None:
    """plan-DD-01: existing scripts/run_hibayes_eval.sh is NOT modified."""
    runtime_wrapper = REPO_ROOT / "scripts" / "run_hibayes_eval.sh"
    assert runtime_wrapper.is_file()
    content = runtime_wrapper.read_text(encoding="utf-8")
    assert "hibayes_runtime_reliability/config" in content
    assert "hibayes_runtime_reliability/templates" in content
