"""tools/hibayes/tests/test_docs_presence.py — documentation presence pinning for T4.4."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_readme_has_hibayes_evaluator_axes_section() -> None:
    """README.md mentions the new evaluator axes."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "HiBayes" in readme
    assert ("hibayes-axes" in readme) or ("hibayes_artifact_validity" in readme)


def test_readme_contains_verbatim_dd25_tempdir_warning() -> None:
    """DL-014 / DD-25: README MUST contain the verbatim DD25_TEMPDIR_WARNING string.

    T4.4 is Wave 4 and merges after T1.1 (Wave 1), which defines the canonical
    `DD25_TEMPDIR_WARNING` constant in `tools/hibayes/artifact_validator.py`.
    The README is the contract surface under DD-07 coverage exception, so the
    pinning test must enforce the FULL warning string verbatim — matching only a
    sub-token (e.g. `artifact_count`) would let a regression pass while violating
    DL-014. Mirrors the T1.1 `--help` pinning pattern.

    `pytest.importorskip` gates gracefully if T1.1's module is somehow absent on
    the executing clone (e.g. a pre-merge Phase 4 dry-run).
    """
    artifact_validator = pytest.importorskip("tools.hibayes.artifact_validator")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert artifact_validator.DD25_TEMPDIR_WARNING in readme, (
        "README.md missing verbatim DD-25 tempdir-mode warning. "
        f"Expected substring:\n{artifact_validator.DD25_TEMPDIR_WARNING}"
    )


def test_changelog_has_new_entry_for_evaluator_expansion() -> None:
    """CHANGELOG.md exists and references the evaluator expansion."""
    changelog = REPO_ROOT / "CHANGELOG.md"
    assert changelog.is_file()
    content = changelog.read_text(encoding="utf-8")
    assert "hibayes-axes" in content or "evaluator expansion" in content.lower()


def test_runtime_axis_readme_cross_references_new_siblings() -> None:
    """src/dmac_assistant/eval/hibayes_runtime_reliability/README.md mentions the new sibling axes."""
    rr_readme = (
        REPO_ROOT / "src" / "dmac_assistant" / "eval" / "hibayes_runtime_reliability" / "README.md"
    )
    if not rr_readme.is_file():
        # If the runtime axis README is absent on this clone, skip cleanly — adding it is
        # outside T4.4's scope (the file lift is a separate refactor). The cross-reference
        # is appended IF the file exists.
        import pytest

        pytest.skip("runtime axis README absent on this clone; cross-reference deferred")
    content = rr_readme.read_text(encoding="utf-8")
    assert (
        "hibayes_artifact_validity" in content
        or "hibayes_functional_usefulness" in content
        or "evaluator expansion" in content.lower()
    )


def test_readme_lists_hibayes_evaluator_expansion_as_complete() -> None:
    """README.md's project status table records the HiBayes evaluator 2-axis
    expansion build plan as complete.

    Replaces the prior `test_claude_md_has_active_plan_line_for_build_plan`
    which read `.claude/CLAUDE.md`. The `.claude/` directory was untracked per
    `.gitignore` intent (originally force-added via `git add -f`); README.md's
    project status table is now the canonical "completed plans" record.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "HiBayes evaluator 2-axis expansion" in readme, (
        "README.md missing the build plan's project status row name."
    )
    assert "✅ **Complete** (2026-05-27)" in readme, (
        "README.md missing the build plan's completion marker (`✅ **Complete** (2026-05-27)`)."
    )
