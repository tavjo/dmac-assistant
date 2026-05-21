"""tools/e2e/tests/test_functional_evaluator_models.py — Pydantic mirror tests for T0.1.

These tests verify the Pydantic v2 models in tools/e2e/functional_evaluator_models.py
match the BAML class declarations field-for-field and enum-value-for-enum-value,
plus structural assertions about the BAML file itself.

The BAML file (.baml) is the runtime authority; Pydantic mirrors are host-side
boundary validation only. Per locked DD-31, three enums (ExpectedBehavior,
ArtifactKind, PrimaryIssue) are declared `@@dynamic` in BAML for runtime extension
via baml-py TypeBuilder; the Pydantic enums here carry the SEED values only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.e2e.functional_evaluator_models import (
    ArtifactKind,
    ArtifactStatus,
    ExpectedBehavior,
    FailureMode,
    FunctionalEvaluation,
    FunctionalEvaluationInput,
    FunctionalOutcome,
    PrimaryIssue,
    ReviewPriority,
)


# -----------------------------------------------------------------------------
# ExpectedBehavior enum (locked DD-16, 6 values; @@dynamic in BAML per DD-31)
# -----------------------------------------------------------------------------

def test_expected_behavior_has_exactly_six_values() -> None:
    assert len(ExpectedBehavior) == 6


def test_expected_behavior_values_match_locked_design() -> None:
    expected = {
        "AnswerDirectly",
        "GenerateArtifact",
        "ClarifyIfAmbiguous",
        "UsePriorContext",
        "StateUnsupportedBoundary",
        "RefuseUnsafeOnly",
    }
    assert {v.value for v in ExpectedBehavior} == expected


# -----------------------------------------------------------------------------
# ArtifactStatus enum (locked DD-16, 10 values incl. PartialAfterFailure per DD-36)
# -----------------------------------------------------------------------------

def test_artifact_status_has_exactly_ten_values() -> None:
    assert len(ArtifactStatus) == 10


def test_artifact_status_values_match_locked_design() -> None:
    expected = {
        "Valid",
        "Missing",
        "Inaccessible",
        "Unreadable",
        "SchemaInvalid",
        "Incomplete",
        "RuntimeFailed",
        "PartialAfterFailure",
        "Indeterminate",
        "NotExpected",
    }
    assert {v.value for v in ArtifactStatus} == expected


# -----------------------------------------------------------------------------
# ArtifactKind enum (locked DD-16, 8 values; @@dynamic in BAML per DD-31)
# -----------------------------------------------------------------------------

def test_artifact_kind_has_exactly_eight_values() -> None:
    assert len(ArtifactKind) == 8


def test_artifact_kind_values_match_locked_design() -> None:
    expected = {
        "GEO_XLSX",
        "SRA_PACKAGE",
        "PRIDE_PACKAGE",
        "NFCORE_RNASEQ_CSV",
        "NFCORE_SCRNASEQ_CSV",
        "SVG_CHART",
        "UNKNOWN_FILE",
        "NONE_EXPECTED",
    }
    assert {v.value for v in ArtifactKind} == expected


# -----------------------------------------------------------------------------
# FunctionalOutcome enum (locked DD-16, 6 values; DD-08 maps subset to success)
# -----------------------------------------------------------------------------

def test_functional_outcome_has_exactly_six_values() -> None:
    assert len(FunctionalOutcome) == 6


def test_functional_outcome_values_match_locked_design() -> None:
    expected = {
        "FullySatisfied",
        "PartiallySatisfied",
        "AppropriateClarification",
        "AppropriateBoundary",
        "NotSatisfied",
        "NotAssessable",
    }
    assert {v.value for v in FunctionalOutcome} == expected


# -----------------------------------------------------------------------------
# PrimaryIssue enum (locked DD-16 + DL-017, 15 values; NoIssue replaces None)
# -----------------------------------------------------------------------------

def test_primary_issue_has_exactly_fifteen_values() -> None:
    assert len(PrimaryIssue) == 15


def test_primary_issue_no_python_keyword_collision() -> None:
    """DL-017: PrimaryIssue.NoIssue (renamed from None) avoids Python-keyword collision."""
    assert PrimaryIssue.NoIssue.value == "NoIssue"
    assert "None" not in {v.value for v in PrimaryIssue}


def test_primary_issue_values_match_locked_design() -> None:
    expected = {
        "NoIssue",
        "RuntimeFailure",
        "Timeout",
        "MissingArtifact",
        "InvalidArtifact",
        "IncompleteArtifact",
        "MissingContext",
        "AmbiguousRequest",
        "OverBroadSearch",
        "UpstreamApiError",
        "UnsupportedRequest",
        "RefusalError",
        "OverclaimedSuccess",
        "InsufficientEvidence",
        "Other",
    }
    assert {v.value for v in PrimaryIssue} == expected


# -----------------------------------------------------------------------------
# ReviewPriority enum (locked DD-16, 3 values)
# -----------------------------------------------------------------------------

def test_review_priority_has_exactly_three_values() -> None:
    assert len(ReviewPriority) == 3


def test_review_priority_values_match_locked_design() -> None:
    assert {v.value for v in ReviewPriority} == {"Low", "Medium", "High"}


# -----------------------------------------------------------------------------
# FailureMode reuse (locked DD-16 explicit "do not duplicate" rule)
# -----------------------------------------------------------------------------

def test_failure_mode_is_imported_from_exporter() -> None:
    """FailureMode must be re-exported from tools.hibayes.exporter (NOT redeclared)."""
    from tools.hibayes.exporter import FailureMode as ExporterFailureMode

    assert FailureMode is ExporterFailureMode
    assert {v.value for v in FailureMode} == {"none", "timeout", "error", "no_answer"}


# -----------------------------------------------------------------------------
# FunctionalEvaluationInput class (locked §7, 11 fields)
# -----------------------------------------------------------------------------

def test_functional_evaluation_input_has_eleven_fields() -> None:
    fields = set(FunctionalEvaluationInput.model_fields.keys())
    expected = {
        "task_family",
        "query_text",
        "final_answer",
        "answer_provided",
        "runtime_success",
        "failure_mode",
        "expected_behavior",
        "artifact_expected",
        "artifact_status",
        "artifact_kind",
        "declared_artifact_count",
    }
    assert fields == expected


def test_functional_evaluation_input_field_types() -> None:
    inp = FunctionalEvaluationInput(
        task_family="Search-Basic",
        query_text="test query",
        final_answer="ok",
        answer_provided=True,
        runtime_success=True,
        failure_mode=FailureMode.none,
        expected_behavior=ExpectedBehavior.AnswerDirectly,
        artifact_expected=False,
        artifact_status=None,
        artifact_kind=None,
        declared_artifact_count=0,
    )
    assert inp.task_family == "Search-Basic"
    assert inp.final_answer == "ok"
    assert inp.failure_mode == FailureMode.none
    assert inp.expected_behavior == ExpectedBehavior.AnswerDirectly
    assert inp.artifact_status is None
    assert inp.artifact_kind is None
    assert inp.declared_artifact_count == 0


def test_functional_evaluation_input_final_answer_nullable() -> None:
    """Locked §7: final_answer is `string?` (nullable)."""
    inp = FunctionalEvaluationInput(
        task_family="Memory",
        query_text="prior context query",
        final_answer=None,
        answer_provided=False,
        runtime_success=False,
        failure_mode=FailureMode.timeout,
        expected_behavior=ExpectedBehavior.UsePriorContext,
        artifact_expected=False,
        artifact_status=None,
        artifact_kind=None,
        declared_artifact_count=0,
    )
    assert inp.final_answer is None


def test_functional_evaluation_input_optional_enums_nullable() -> None:
    """Locked §7: artifact_status and artifact_kind are optional (BAML `?` suffix)."""
    inp = FunctionalEvaluationInput(
        task_family="Report-GEO",
        query_text="generate GEO",
        final_answer="see attached",
        answer_provided=True,
        runtime_success=True,
        failure_mode=FailureMode.none,
        expected_behavior=ExpectedBehavior.GenerateArtifact,
        artifact_expected=True,
        artifact_status=ArtifactStatus.Valid,
        artifact_kind=ArtifactKind.GEO_XLSX,
        declared_artifact_count=1,
    )
    assert inp.artifact_status == ArtifactStatus.Valid
    assert inp.artifact_kind == ArtifactKind.GEO_XLSX


# -----------------------------------------------------------------------------
# FunctionalEvaluation class (locked §7, 6 fields)
# -----------------------------------------------------------------------------

def test_functional_evaluation_has_six_fields() -> None:
    fields = set(FunctionalEvaluation.model_fields.keys())
    expected = {
        "outcome",
        "usefulness_score",
        "primary_issue",
        "needs_human_review",
        "review_priority",
        "rationale",
    }
    assert fields == expected


def test_functional_evaluation_usefulness_score_accepts_in_range() -> None:
    """Locked §7: usefulness_score is int in [0, 4]."""
    for score in (0, 1, 2, 3, 4):
        fe = FunctionalEvaluation(
            outcome=FunctionalOutcome.FullySatisfied,
            usefulness_score=score,
            primary_issue=PrimaryIssue.NoIssue,
            needs_human_review=False,
            review_priority=ReviewPriority.Low,
            rationale="Test rationale.",
        )
        assert fe.usefulness_score == score


def test_functional_evaluation_usefulness_score_rejects_above_max() -> None:
    with pytest.raises(Exception):
        FunctionalEvaluation(
            outcome=FunctionalOutcome.FullySatisfied,
            usefulness_score=5,
            primary_issue=PrimaryIssue.NoIssue,
            needs_human_review=False,
            review_priority=ReviewPriority.Low,
            rationale="Test rationale.",
        )


def test_functional_evaluation_usefulness_score_rejects_below_min() -> None:
    with pytest.raises(Exception):
        FunctionalEvaluation(
            outcome=FunctionalOutcome.NotSatisfied,
            usefulness_score=-1,
            primary_issue=PrimaryIssue.RuntimeFailure,
            needs_human_review=True,
            review_priority=ReviewPriority.High,
            rationale="Test rationale.",
        )


# -----------------------------------------------------------------------------
# BAML file structural assertions (locked DD-22 + DD-31 + DD-32)
# -----------------------------------------------------------------------------

def _baml_path() -> Path:
    # cc2c43b BAML consolidation: source lives at repo-root `baml_src/`, not `tools/e2e/baml_src/`.
    # This test file is at `tools/e2e/tests/`; parents[3] is the repo root.
    return Path(__file__).resolve().parents[3] / "baml_src" / "functional_evaluator.baml"


def test_baml_file_exists_at_expected_path() -> None:
    assert _baml_path().is_file()


def test_baml_file_declares_dynamic_on_three_extensible_enums() -> None:
    """Locked DD-31: ExpectedBehavior, ArtifactKind, PrimaryIssue must carry @@dynamic."""
    content = _baml_path().read_text(encoding="utf-8")
    for enum_name in ("ExpectedBehavior", "ArtifactKind", "PrimaryIssue"):
        assert f"enum {enum_name}" in content, f"BAML missing enum {enum_name}"
    assert content.count("@@dynamic") >= 3, (
        f"Expected ≥3 `@@dynamic` markers (per DD-31), found {content.count('@@dynamic')}"
    )


def test_baml_file_reuses_gcpreasoner_client_without_redeclaring() -> None:
    """Locked DD-32 as amended by AM-002 / drift D-6: Stage C REUSES the canonical
    `client<llm> GCPReasoner` (declared in `baml_src/clients.baml`) and declares NO
    new client of its own. functional_evaluator.baml must NOT contain a `client<llm>`
    block (that would `DuplicateTopLevel`-fail codegen against clients.baml, or — if
    named differently — duplicate the canonical Gemini wiring)."""
    content = _baml_path().read_text(encoding="utf-8")
    # No `client<llm>` declaration block in this file.
    assert "client<llm>" not in content, (
        "functional_evaluator.baml must not declare a client<llm> block — "
        "Stage C reuses GCPReasoner from baml_src/clients.baml (AM-002 / D-6)"
    )
    # The legacy `FunctionalEvaluator` client name is fully retired.
    assert "FunctionalEvaluator" not in content
    # The function references the canonical client by name.
    assert "client GCPReasoner" in content


def test_baml_file_declares_evaluate_functional_usefulness_function() -> None:
    """Locked §7: EvaluateFunctionalUsefulness function defined."""
    content = _baml_path().read_text(encoding="utf-8")
    assert (
        "function EvaluateFunctionalUsefulness(input: FunctionalEvaluationInput) -> FunctionalEvaluation"
        in content
    )
    assert "client GCPReasoner" in content


def test_baml_file_includes_seven_dd22_prompt_rules() -> None:
    """Locked DD-22: all 7 non-negotiable prompt rules embedded in the function's prompt block."""
    content = _baml_path().read_text(encoding="utf-8")
    rule_keywords = [
        "functional usefulness",            # Rule 1
        "invent",                           # Rule 2
        "runtime cost",                     # Rule 3
        "GenerateArtifact",                 # Rule 4
        "runtime_success",                  # Rule 5
        "Incomplete, Missing, SchemaInvalid, RuntimeFailed",  # Rule 6
        "Clarification",                    # Rule 7
    ]
    for kw in rule_keywords:
        assert kw in content, f"BAML prompt missing DD-22 rule keyword: {kw}"


# -----------------------------------------------------------------------------
# BAML codegen end-to-end (catches grammar errors like lowercase enum identifiers
# that would slip past text-grep assertions and only blow up at image-build time).
# -----------------------------------------------------------------------------

def test_baml_cli_generate_succeeds_end_to_end(tmp_path: Path) -> None:
    """Invoke `baml-cli generate` against the real baml_src tree and assert the
    generated Python client is importable.

    This is the structural gate that catches BAML grammar defects (e.g. lowercase
    enum value identifiers) which would pass every text-grep test above but fail
    at `baml-cli generate` time. Patterned after the router task's merge-condition
    proof in `tests/unit/router/test_t11_merge_conditions.py` — but invoked here
    as a subprocess so we don't depend on a pre-generated `baml_client/` tree
    (which is gitignored per `.gitignore:46` and only materialized at image-build).
    """
    import importlib.util
    import shutil
    import subprocess
    import sys

    baml_src = _baml_path().parent  # repo-root baml_src/ (cc2c43b consolidation)
    repo_root = baml_src.parents[0]  # baml_src/ sits directly under the repo root
    # Stage baml_src into tmp_path so codegen output lands under tmp_path, not the
    # real source tree. The consolidated `baml_src/generators.baml` declares TWO
    # generator targets — `router_target` (output_dir "../src/dmac_assistant/router/")
    # and `e2e_target` (output_dir "../tools/e2e/"). Both are relative to the staged
    # baml_src/, so codegen writes `tmp_path/src/dmac_assistant/router/baml_client/`
    # and `tmp_path/tools/e2e/baml_client/`. Stage C consumes the e2e_target output.
    staged_src = tmp_path / "baml_src"
    shutil.copytree(baml_src, staged_src)

    result = subprocess.run(
        ["uv", "run", "baml-cli", "generate", "--from", str(staged_src)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"baml-cli generate failed (exit {result.returncode}).\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    # e2e_target output_dir "../tools/e2e/" relative to staged baml_src/ → tmp_path/tools/e2e/baml_client/.
    generated_init = tmp_path / "tools" / "e2e" / "baml_client" / "__init__.py"
    assert generated_init.is_file(), (
        f"baml-cli generate produced no e2e baml_client/__init__.py at {generated_init}"
    )

    # Load the generated package by file path so we don't pollute the real
    # tools/e2e/baml_client/ namespace or rely on sys.path tricks.
    spec = importlib.util.spec_from_file_location(
        "_t01_generated_baml_client", generated_init
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
