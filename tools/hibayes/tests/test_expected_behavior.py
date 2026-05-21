"""tools/hibayes/tests/test_expected_behavior.py — pinning tests for T0.2.

Tests the 22-row task_family → ExpectedBehavior mapping per locked DD-30 +
DL-021. Hardened per build-plan DL-027 (executor-forcing pinning) and
Path B / DL-029 (AnswerDirectly: 13 per row enumeration; ESC-1 documented).

Per project memory `feedback_categorize_with_full_corpus_context.md` 2026-05-15:
Write-Create and Write-Update both resolve to RefuseUnsafeOnly (NOT
ClarifyIfAmbiguous), rationale anchored to the `Write-safety on NExtSEEK` paragraph of `container/CLAUDE.md`.
"""
from __future__ import annotations

from collections import Counter

import pytest

from tools.hibayes.enums import ExpectedBehavior
from tools.hibayes.expected_behavior import (
    EXPECTED_BEHAVIOR_BY_FAMILY,
    FAMILIES_22,
    expected_behavior_rule,
)


# -----------------------------------------------------------------------------
# 22-row parameterized pinning test (DL-027 executor-forcing format)
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task_family,expected",
    [
        ("Edge", ExpectedBehavior.AnswerDirectly),
        ("Graph-Assay", ExpectedBehavior.AnswerDirectly),
        ("Graph-Count", ExpectedBehavior.AnswerDirectly),
        ("Graph-Lineage", ExpectedBehavior.AnswerDirectly),
        ("Graph-Study", ExpectedBehavior.AnswerDirectly),
        ("Memory", ExpectedBehavior.UsePriorContext),
        ("Report-GEO", ExpectedBehavior.GenerateArtifact),
        ("Report-NFCORE", ExpectedBehavior.GenerateArtifact),
        ("Report-PRIDE", ExpectedBehavior.GenerateArtifact),
        ("Report-SRA", ExpectedBehavior.GenerateArtifact),
        ("Reporter-Summary", ExpectedBehavior.AnswerDirectly),
        ("Retrieve", ExpectedBehavior.AnswerDirectly),
        ("SampleTree", ExpectedBehavior.AnswerDirectly),
        ("Search-Attribute", ExpectedBehavior.AnswerDirectly),
        ("Search-Basic", ExpectedBehavior.AnswerDirectly),
        ("Search-MultiAssay", ExpectedBehavior.AnswerDirectly),
        ("Search-Refine", ExpectedBehavior.UsePriorContext),
        ("System-Capabilities", ExpectedBehavior.AnswerDirectly),
        ("System-Entity", ExpectedBehavior.AnswerDirectly),
        ("Unsupported", ExpectedBehavior.StateUnsupportedBoundary),
        ("Write-Create", ExpectedBehavior.RefuseUnsafeOnly),
        ("Write-Update", ExpectedBehavior.RefuseUnsafeOnly),
    ],
)
def test_expected_behavior_rule_returns_locked_value_for_each_22_family(
    task_family: str, expected: ExpectedBehavior
) -> None:
    """DL-021 + DL-029: rule function returns the locked ExpectedBehavior for each of 22 families."""
    assert expected_behavior_rule(task_family) == expected


# -----------------------------------------------------------------------------
# Domain-completeness: exactly 22 strings
# -----------------------------------------------------------------------------

def test_families_22_constant_has_exactly_22_strings() -> None:
    """The FAMILIES_22 module constant pins the rule's input domain."""
    assert len(FAMILIES_22) == 22


def test_families_22_strings_are_unique() -> None:
    """No duplicate task_family strings in the canonical list."""
    assert len(FAMILIES_22) == len(set(FAMILIES_22))


def test_expected_behavior_by_family_dict_has_22_entries() -> None:
    """The dict mirrors the 22-row mapping; len must be exactly 22."""
    assert len(EXPECTED_BEHAVIOR_BY_FAMILY) == 22


def test_expected_behavior_by_family_keys_equal_families_22() -> None:
    """The dict's keys are exactly the FAMILIES_22 strings."""
    assert set(EXPECTED_BEHAVIOR_BY_FAMILY.keys()) == set(FAMILIES_22)


# -----------------------------------------------------------------------------
# Enum-distribution check (Path B / DL-029): AnswerDirectly: 13 per row enumeration
# -----------------------------------------------------------------------------

def test_enum_distribution_matches_path_b_locked_row_enumeration() -> None:
    """Path B / DL-029: distribution per row-by-row enumeration of locked-design lines 295-316.

    Diverges from locked-design line 318's summary `AnswerDirectly (14 families)` because
    that line is an arithmetic-error summary; the operative row enumeration contains
    exactly 13 AnswerDirectly entries (rows 1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 16, 18, 19).
    Per the Phase-4 authority hierarchy (locked design > plan; within the locked design,
    the per-row mapping the executor implements is operative over a summary count),
    the row enumeration is canonical. See build-plan DL-029 + ESC-1.

    Sum = 13 + 4 + 2 + 1 + 2 = 22.
    """
    distribution = Counter(expected_behavior_rule(fam) for fam in FAMILIES_22)
    assert distribution == Counter(
        {
            ExpectedBehavior.AnswerDirectly: 13,
            ExpectedBehavior.GenerateArtifact: 4,
            ExpectedBehavior.UsePriorContext: 2,
            ExpectedBehavior.StateUnsupportedBoundary: 1,
            ExpectedBehavior.RefuseUnsafeOnly: 2,
        }
    )
    assert sum(distribution.values()) == 22


# -----------------------------------------------------------------------------
# Coarse-default semantics for `Unsupported` (DL-013 / R15)
# -----------------------------------------------------------------------------

def test_unsupported_family_returns_state_unsupported_boundary() -> None:
    """DL-013 / R15: coarse default for heterogeneous Unsupported family."""
    assert (
        expected_behavior_rule("Unsupported")
        == ExpectedBehavior.StateUnsupportedBoundary
    )


def test_unsupported_family_docstring_documents_known_accuracy_loss() -> None:
    """DL-013 / R15: the docstring or module docstring must document the R15 accuracy loss."""
    import tools.hibayes.expected_behavior as eb_mod

    # Either the module docstring or the function docstring (or both) must mention R15.
    docs = "\n".join(
        filter(
            None,
            [
                eb_mod.__doc__,
                expected_behavior_rule.__doc__,
            ],
        )
    )
    # Look for the substring "R15" or "coarse" or "Unsupported" + "accuracy" in docs.
    assert (
        "R15" in docs
        or ("coarse" in docs.lower() and "Unsupported" in docs)
        or ("Unsupported" in docs and "accuracy" in docs.lower())
    ), (
        f"Module/function docstring must document R15 coarse-default accuracy loss "
        f"for Unsupported family. Docs:\n{docs}"
    )


# -----------------------------------------------------------------------------
# Write-* families: RefuseUnsafeOnly (NOT ClarifyIfAmbiguous)
# -----------------------------------------------------------------------------

def test_write_create_resolves_to_refuse_unsafe_only() -> None:
    """Project memory feedback_categorize_with_full_corpus_context.md 2026-05-15."""
    assert (
        expected_behavior_rule("Write-Create") == ExpectedBehavior.RefuseUnsafeOnly
    )


def test_write_update_resolves_to_refuse_unsafe_only() -> None:
    """Same write-safety policy as Write-Create per DL-021."""
    assert (
        expected_behavior_rule("Write-Update") == ExpectedBehavior.RefuseUnsafeOnly
    )


# -----------------------------------------------------------------------------
# Unknown-family handling (DD-30)
# -----------------------------------------------------------------------------

def test_unknown_family_raises_known_error() -> None:
    """DD-30: an unknown family raises a KeyError or returns a documented sentinel.

    The rule function's contract is that the input domain is exactly the 22-string
    FAMILIES_22 list. A 23rd input is a defect in the caller; the rule MUST signal
    loudly rather than silently returning a default.
    """
    with pytest.raises(KeyError):
        expected_behavior_rule("DefinitelyNotARealFamily")


# -----------------------------------------------------------------------------
# Enum surface (tools/hibayes/enums.py re-exports)
# -----------------------------------------------------------------------------

def test_enums_module_re_exports_failure_mode() -> None:
    """tools/hibayes/enums.py re-exports FailureMode from the exporter."""
    from tools.hibayes.enums import FailureMode as ReexportedFailureMode
    from tools.hibayes.exporter import FailureMode as ExporterFailureMode

    assert ReexportedFailureMode is ExporterFailureMode


def test_enums_module_re_exports_all_six_new_enums() -> None:
    """tools/hibayes/enums.py re-exports ExpectedBehavior + 5 others from T0.1's mirror file."""
    from tools.hibayes import enums as hbe

    for name in (
        "ExpectedBehavior",
        "ArtifactStatus",
        "ArtifactKind",
        "FunctionalOutcome",
        "PrimaryIssue",
        "ReviewPriority",
    ):
        assert hasattr(hbe, name), f"tools.hibayes.enums missing re-export: {name}"


def test_enums_module_expected_behavior_is_same_class_as_t01_mirror() -> None:
    """Single source of truth: the ExpectedBehavior class in enums.py IS the one in functional_evaluator_models."""
    from tools.e2e.functional_evaluator_models import ExpectedBehavior as T01_ExpectedBehavior
    from tools.hibayes.enums import ExpectedBehavior as T02_ExpectedBehavior

    assert T01_ExpectedBehavior is T02_ExpectedBehavior
