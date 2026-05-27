"""tools/e2e/tests/test_functional_evaluator.py — mocked tests for T2.1 Stage C.

All BAML calls are mocked; --disable-socket enforces the discipline. Live tests
live in test_functional_evaluator_live.py (T2.2).
"""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.e2e.functional_evaluator import (
    FUNCTIONAL_USEFULNESS_HEADER_12,
    REVIEW_SIDECAR_HEADER_12,
    STAGE_C_STATUS_COMPLETE,
    STAGE_C_STATUS_FAILED,
    STAGE_C_STATUS_PARTIAL,
    _collect_dynamic_enum_extensions,
    aggregate_outcome,
    aggregate_primary_issue,
    aggregate_review_priority,
    build_input_kwargs_from_row,
    main,
    run_stage_c,
)
from tools.e2e.functional_evaluator_models import (
    FunctionalEvaluation,
    FunctionalEvaluationInput,
    FunctionalOutcome,
    PrimaryIssue,
    ReviewPriority,
)


# -----------------------------------------------------------------------------
# Header pinning (locked §5.3 + DD-43)
# -----------------------------------------------------------------------------

EXPECTED_USEFULNESS_HEADER = [
    "query_id",
    "task_family",
    "expected_behavior",
    "runtime_success",
    "artifact_status",
    "outcome",
    "usefulness_score",
    "primary_issue",
    "functional_success",
    "needs_human_review",
    "review_priority",
    "rationale",
]

EXPECTED_SIDECAR_HEADER = [
    "query_id",
    "task_family",
    "query_text",
    "final_answer",
    "validation_notes",
    "aggregated_outcome",
    "aggregated_usefulness_score",
    "aggregated_primary_issue",
    "aggregated_rationale",
    "all_3_judgments_json",
    "stage_c_call_count",
    "stage_c_status",
]


def test_functional_usefulness_header_is_locked_design() -> None:
    """Locked §5.3: 12 columns in exact order."""
    assert list(FUNCTIONAL_USEFULNESS_HEADER_12) == EXPECTED_USEFULNESS_HEADER


def test_review_sidecar_header_is_locked_dd43() -> None:
    """Locked DD-43: 12 columns in exact order."""
    assert list(REVIEW_SIDECAR_HEADER_12) == EXPECTED_SIDECAR_HEADER


# -----------------------------------------------------------------------------
# DD-44 outcome aggregation pseudocode (locked design lines 442-471 verbatim)
# -----------------------------------------------------------------------------

def test_aggregate_outcome_2_to_1_majority_wins_regardless_of_partition() -> None:
    """DD-44: 2-1 majority wins regardless of partition."""
    votes = (
        FunctionalOutcome.NotSatisfied.value,
        FunctionalOutcome.AppropriateClarification.value,
        FunctionalOutcome.AppropriateClarification.value,
    )
    assert aggregate_outcome(votes) == FunctionalOutcome.AppropriateClarification.value


def test_aggregate_outcome_3_to_0_unanimous() -> None:
    votes = (
        FunctionalOutcome.FullySatisfied.value,
        FunctionalOutcome.FullySatisfied.value,
        FunctionalOutcome.FullySatisfied.value,
    )
    assert aggregate_outcome(votes) == FunctionalOutcome.FullySatisfied.value


def test_aggregate_outcome_all_distinct_failure_partition_first() -> None:
    """DD-44: all-three-different falls through to failure-partition-first."""
    votes = (
        FunctionalOutcome.NotAssessable.value,
        FunctionalOutcome.AppropriateClarification.value,
        FunctionalOutcome.AppropriateBoundary.value,
    )
    # NotAssessable is failure-side; both others are success-side. Failure wins.
    assert aggregate_outcome(votes) == FunctionalOutcome.NotAssessable.value


def test_aggregate_outcome_all_distinct_success_partition_strict_order() -> None:
    votes = (
        FunctionalOutcome.AppropriateClarification.value,
        FunctionalOutcome.AppropriateBoundary.value,
        FunctionalOutcome.FullySatisfied.value,
    )
    # All success-side; AppropriateClarification has lowest STRICT_ORDER → 3.
    assert aggregate_outcome(votes) == FunctionalOutcome.AppropriateClarification.value


# -----------------------------------------------------------------------------
# DD-44 primary_issue aggregation (majority with severity tie-break)
# -----------------------------------------------------------------------------

def test_aggregate_primary_issue_majority() -> None:
    votes = (
        PrimaryIssue.RuntimeFailure.value,
        PrimaryIssue.RuntimeFailure.value,
        PrimaryIssue.NoIssue.value,
    )
    assert aggregate_primary_issue(votes) == PrimaryIssue.RuntimeFailure.value


def test_aggregate_primary_issue_three_way_tie_severity_wins() -> None:
    """Tie-break is severity order: RuntimeFailure > Timeout > MissingArtifact > ... > NoIssue."""
    votes = (
        PrimaryIssue.Timeout.value,
        PrimaryIssue.RuntimeFailure.value,
        PrimaryIssue.NoIssue.value,
    )
    # All distinct; severity rank: RuntimeFailure has the highest severity → wins.
    assert aggregate_primary_issue(votes) == PrimaryIssue.RuntimeFailure.value


# -----------------------------------------------------------------------------
# DD-44 review_priority aggregation (max)
# -----------------------------------------------------------------------------

def test_aggregate_review_priority_max() -> None:
    votes = (
        ReviewPriority.Low.value,
        ReviewPriority.High.value,
        ReviewPriority.Medium.value,
    )
    assert aggregate_review_priority(votes) == ReviewPriority.High.value


# -----------------------------------------------------------------------------
# KEYWORD-argument construction (locked §5.2 post-table note)
# -----------------------------------------------------------------------------

def test_build_input_kwargs_from_row_uses_correct_field_names() -> None:
    """Regression: a row whose CSV order differs from BAML field order must construct via kwargs.

    The CSV puts `expected_behavior` LAST; the BAML class has it 7th. If the runner
    constructed positionally, `expected_behavior` would be silently swapped with
    `artifact_expected`/`artifact_status`/`artifact_kind`/`declared_artifact_count`.
    """
    csv_row = {
        "query_id": "Search-Basic-1",
        "task_family": "Search-Basic",
        "query_text": "test",
        "final_answer": "ok",
        "answer_provided": "True",
        "runtime_success": "True",
        "failure_mode": "none",
        "artifact_expected": "False",
        "artifact_status": "",
        "artifact_kind": "",
        "declared_artifact_count": "0",
        "expected_behavior": "AnswerDirectly",
    }
    kwargs = build_input_kwargs_from_row(csv_row)
    inp = FunctionalEvaluationInput(**kwargs)
    assert inp.task_family == "Search-Basic"
    assert inp.expected_behavior.value == "AnswerDirectly"  # NOT swapped with another field
    assert inp.artifact_expected is False
    assert inp.declared_artifact_count == 0
    assert inp.artifact_status is None
    assert inp.artifact_kind is None


def test_build_input_kwargs_coerces_empty_failure_mode_to_none() -> None:
    """FR-1 regression (Wave 1 reviewer): Stage B emits failure_mode="" (empty
    STRING, not a missing key) for any query absent from the runtime CSV. A bare
    `row.get("failure_mode", "none")` returns "" — its default only fires on a
    MISSING key — and "" then fails the typed `FailureMode` enum, crashing the
    query instead of producing a partial-failure row.

    `build_input_kwargs_from_row` must coerce an empty `failure_mode` (and the
    sibling typed-enum `expected_behavior`) to their valid seed defaults so the
    typed `FunctionalEvaluationInput` constructs without raising.
    """
    csv_row = {
        "query_id": "Search-Basic-2",
        "task_family": "Search-Basic",
        "query_text": "test",
        "final_answer": "ok",
        "answer_provided": "True",
        "runtime_success": "True",
        "failure_mode": "",          # empty STRING, not a missing key
        "artifact_expected": "False",
        "artifact_status": "",
        "artifact_kind": "",
        "declared_artifact_count": "0",
        "expected_behavior": "",     # empty STRING, not a missing key
    }
    kwargs = build_input_kwargs_from_row(csv_row)
    # The coerced values must be valid seed-enum members, not "".
    assert kwargs["failure_mode"] == "none"
    assert kwargs["expected_behavior"] == "AnswerDirectly"
    # Constructing the typed input must NOT raise a Pydantic ValidationError.
    inp = FunctionalEvaluationInput(**kwargs)
    assert inp.failure_mode.value == "none"
    assert inp.expected_behavior.value == "AnswerDirectly"


# -----------------------------------------------------------------------------
# run_stage_c: end-to-end mocked smoke (happy path — all 3 calls succeed)
# -----------------------------------------------------------------------------

def _seed_inputs(tmp_path: Path) -> tuple[Path, Path]:
    fei_csv = tmp_path / "fei.csv"
    fei_csv.write_text(
        ",".join(EXPECTED_USEFULNESS_HEADER[:1] + [
            "task_family", "query_text", "final_answer", "answer_provided",
            "runtime_success", "failure_mode", "artifact_expected", "artifact_status",
            "artifact_kind", "declared_artifact_count", "expected_behavior",
        ]) + "\n"
        "Search-Basic-1,Search-Basic,find X,ok,True,True,none,False,,,0,AnswerDirectly\n"
    )
    av_csv = tmp_path / "av.csv"
    av_csv.write_text(
        "query_id,task_family,validation_notes\n"
        "Search-Basic-1,Search-Basic,clean\n"
    )
    return fei_csv, av_csv


def _make_evaluation(
    outcome: str = "FullySatisfied",
    score: int = 4,
    issue: str = "NoIssue",
    priority: str = "Low",
    needs_review: bool = False,
    rationale: str = "OK.",
) -> FunctionalEvaluation:
    return FunctionalEvaluation(
        outcome=FunctionalOutcome(outcome),
        usefulness_score=score,
        primary_issue=PrimaryIssue(issue),
        needs_human_review=needs_review,
        review_priority=ReviewPriority(priority),
        rationale=rationale,
    )


@pytest.fixture(autouse=True)
def _stub_typebuilder_for_unit_tests(request: pytest.FixtureRequest):
    """Autouse fixture: patch `_build_typebuilder_for_query` to return a sentinel
    object so unit tests do NOT require the generated `baml_client.type_builder`
    module to be importable. The DD-31 identity-share test opts out of this
    fixture (it patches the function itself with its own sentinel).
    """
    if "no_autostub_tb" in request.keywords:
        yield
        return
    with patch(
        "tools.e2e.functional_evaluator._build_typebuilder_for_query",
        MagicMock(return_value=object()),
    ):
        yield


def test_run_stage_c_happy_path_all_3_calls_succeed(tmp_path: Path) -> None:
    fei_csv, av_csv = _seed_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    fake_eval = _make_evaluation()
    mock_invoke = MagicMock(return_value=fake_eval)

    with patch("tools.e2e.functional_evaluator._invoke_baml_evaluator", mock_invoke):
        exit_code = run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )
    assert exit_code == 0
    assert mock_invoke.call_count == 3  # 3 calls per query × 1 query

    with fu_csv.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "FullySatisfied"
    assert rows[0]["functional_success"] in ("True", "true")  # DD-08

    with sidecar_csv.open("r", encoding="utf-8") as fh:
        sidecar_rows = list(csv.DictReader(fh))
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["stage_c_call_count"] == "3"
    assert sidecar_rows[0]["stage_c_status"] == STAGE_C_STATUS_COMPLETE


# -----------------------------------------------------------------------------
# Partial-failure semantics (DD-43)
# -----------------------------------------------------------------------------

def test_run_stage_c_all_3_calls_fail_exit_nonzero(tmp_path: Path) -> None:
    """DD-43: stage_c_call_count == 0 → exit non-zero (unless --allow-partial-stage-c)."""
    fei_csv, av_csv = _seed_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    mock_invoke = MagicMock(side_effect=Exception("BAML rate limit"))

    with patch("tools.e2e.functional_evaluator._invoke_baml_evaluator", mock_invoke):
        exit_code = run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )
    assert exit_code != 0
    # Usefulness CSV is deleted on failure so GNU make / other timestamp-based
    # callers cannot treat partial output as a valid cached target. Sidecar
    # preserved for debug inspection.
    assert not fu_csv.exists()
    with sidecar_csv.open("r", encoding="utf-8") as fh:
        sidecar_rows = list(csv.DictReader(fh))
    assert sidecar_rows[0]["stage_c_call_count"] == "0"
    assert sidecar_rows[0]["stage_c_status"] == STAGE_C_STATUS_FAILED
    assert sidecar_rows[0]["aggregated_outcome"] == "NotAssessable"
    assert sidecar_rows[0]["aggregated_primary_issue"] == "RuntimeFailure"
    assert "3 of 3" in sidecar_rows[0]["aggregated_rationale"]


def test_run_stage_c_allow_partial_returns_zero_despite_failure(tmp_path: Path) -> None:
    """DD-43: --allow-partial-stage-c overrides non-zero exit."""
    fei_csv, av_csv = _seed_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    mock_invoke = MagicMock(side_effect=Exception("BAML rate limit"))

    with patch("tools.e2e.functional_evaluator._invoke_baml_evaluator", mock_invoke):
        exit_code = run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=True,
        )
    assert exit_code == 0


def test_run_stage_c_partial_success_1_of_3(tmp_path: Path) -> None:
    """DD-43: stage_c_call_count == 1 → PartialSuccess."""
    fei_csv, av_csv = _seed_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    fake_eval = _make_evaluation()
    mock_invoke = MagicMock(side_effect=[fake_eval, Exception("fail"), Exception("fail")])

    with patch("tools.e2e.functional_evaluator._invoke_baml_evaluator", mock_invoke):
        exit_code = run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )
    assert exit_code != 0  # PartialSuccess still exits non-zero by default
    # Usefulness CSV deleted on PartialSuccess too (same return-1 path).
    assert not fu_csv.exists()
    with sidecar_csv.open("r", encoding="utf-8") as fh:
        sidecar_rows = list(csv.DictReader(fh))
    assert sidecar_rows[0]["stage_c_call_count"] == "1"
    assert sidecar_rows[0]["stage_c_status"] == STAGE_C_STATUS_PARTIAL


# -----------------------------------------------------------------------------
# Sidecar joins Stage A validation_notes
# -----------------------------------------------------------------------------

def test_sidecar_joins_validation_notes_from_artifact_csv(tmp_path: Path) -> None:
    """DL-021: sidecar's validation_notes column comes from Stage A's artifact CSV."""
    fei_csv = tmp_path / "fei.csv"
    fei_csv.write_text(
        "query_id,task_family,query_text,final_answer,answer_provided,runtime_success,failure_mode,artifact_expected,artifact_status,artifact_kind,declared_artifact_count,expected_behavior\n"
        "Report-GEO-1,Report-GEO,gen GEO,see attached,True,True,none,True,Valid,GEO_XLSX,1,GenerateArtifact\n"
    )
    av_csv = tmp_path / "av.csv"
    av_csv.write_text(
        "query_id,task_family,validation_notes\n"
        "Report-GEO-1,Report-GEO,sheet1 valid; required fields present\n"
    )
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"
    fake_eval = _make_evaluation()
    with patch(
        "tools.e2e.functional_evaluator._invoke_baml_evaluator",
        MagicMock(return_value=fake_eval),
    ):
        run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )
    sidecar_rows = list(csv.DictReader(sidecar_csv.open(encoding="utf-8")))
    assert sidecar_rows[0]["validation_notes"] == "sheet1 valid; required fields present"
    assert sidecar_rows[0]["query_text"] == "gen GEO"
    assert sidecar_rows[0]["final_answer"] == "see attached"


# -----------------------------------------------------------------------------
# DD-08 functional_success derivation
# -----------------------------------------------------------------------------

def test_functional_success_true_for_appropriate_clarification(tmp_path: Path) -> None:
    """DD-08: functional_success = outcome ∈ {FullySatisfied, AppropriateClarification, AppropriateBoundary}."""
    fei_csv = tmp_path / "fei.csv"
    fei_csv.write_text(
        "query_id,task_family,query_text,final_answer,answer_provided,runtime_success,failure_mode,artifact_expected,artifact_status,artifact_kind,declared_artifact_count,expected_behavior\n"
        "Edge-1,Edge,clarify needed,need detail,True,True,none,False,,,0,AnswerDirectly\n"
    )
    av_csv = tmp_path / "av.csv"
    av_csv.write_text("query_id,task_family,validation_notes\nEdge-1,Edge,\n")
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"
    fake_eval = _make_evaluation(outcome="AppropriateClarification", issue="NoIssue")
    with patch(
        "tools.e2e.functional_evaluator._invoke_baml_evaluator",
        MagicMock(return_value=fake_eval),
    ):
        run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )
    fu_rows = list(csv.DictReader(fu_csv.open(encoding="utf-8")))
    assert fu_rows[0]["functional_success"] in ("True", "true")


# -----------------------------------------------------------------------------
# `--max-parallel-queries` flag exists (DD-44 / R5)
# -----------------------------------------------------------------------------

def test_max_parallel_queries_default_is_4() -> None:
    """DD-44: default 4 (R5 mitigation envelope)."""
    import argparse  # noqa: F401

    from tools.e2e.functional_evaluator import build_arg_parser

    parser = build_arg_parser()
    args = parser.parse_args(["--fei-csv", "x", "--av-csv", "y", "--out-usefulness", "z", "--out-sidecar", "w"])
    assert args.max_parallel_queries == 4


# -----------------------------------------------------------------------------
# DD-31 TypeBuilder per-query construction (one shared TypeBuilder across 3 calls)
# -----------------------------------------------------------------------------

@pytest.mark.no_autostub_tb
def test_process_one_query_uses_shared_typebuilder(tmp_path: Path) -> None:
    """Locked DD-31: per query, the runner constructs ONE TypeBuilder instance
    and reuses it across all three sequential BAML calls for that query.

    Verifies via `mock_invoke.call_args_list[i].args[1]` that the SAME object
    identity is forwarded to each of the 3 calls. `_build_typebuilder_for_query`
    is also patched to return a sentinel so the test does not require a
    generated `baml_client` package to be importable. Opts out of the autouse
    stub fixture so this test owns the `_build_typebuilder_for_query` mock and
    can assert `call_count == 1`.
    """
    fei_csv, av_csv = _seed_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    fake_eval = _make_evaluation()
    mock_invoke = MagicMock(return_value=fake_eval)
    sentinel_tb = object()
    mock_build_tb = MagicMock(return_value=sentinel_tb)

    with patch(
        "tools.e2e.functional_evaluator._invoke_baml_evaluator", mock_invoke,
    ), patch(
        "tools.e2e.functional_evaluator._build_typebuilder_for_query", mock_build_tb,
    ):
        run_stage_c(
            fei_csv_path=fei_csv,
            artifact_csv_path=av_csv,
            out_usefulness_csv=fu_csv,
            out_sidecar_csv=sidecar_csv,
            max_parallel_queries=1,
            allow_partial=False,
        )

    # Exactly ONE TypeBuilder constructed for the single query in _seed_inputs.
    assert mock_build_tb.call_count == 1
    assert mock_invoke.call_count == 3
    # Each call forwards the SAME TypeBuilder object (positional arg index 1).
    tb_values = [
        (call.kwargs["tb"] if "tb" in call.kwargs else call.args[1])
        for call in mock_invoke.call_args_list
    ]
    assert tb_values[0] is sentinel_tb
    assert tb_values[0] is tb_values[1] is tb_values[2], (
        "DD-31 violation: TypeBuilder identity is NOT shared across the 3 sequential "
        "BAML calls for a single query."
    )


def test_collect_dynamic_enum_extensions_picks_up_novel_value() -> None:
    """DD-31 step 1: corpus-load-time scan collects `expected_behavior` values
    that are NOT in the BAML seed enum.
    """
    rows = [
        {"expected_behavior": "AnswerDirectly"},   # in seed
        {"expected_behavior": "FutureNovelValue"},  # NOT in seed
        {"expected_behavior": "AnswerDirectly"},
    ]
    extensions = _collect_dynamic_enum_extensions(rows)
    assert "FutureNovelValue" in extensions["ExpectedBehavior"]
    assert "AnswerDirectly" not in extensions["ExpectedBehavior"]
    # ArtifactKind and PrimaryIssue extension sets are seeded as empty for
    # uniform downstream handling.
    assert extensions["ArtifactKind"] == set()
    assert extensions["PrimaryIssue"] == set()


def test_collect_dynamic_enum_extensions_empty_corpus_yields_empty_sets() -> None:
    """Empty corpus → no extensions. The map is still shaped consistently so
    `_build_typebuilder_for_query` works on it without `KeyError`.
    """
    extensions = _collect_dynamic_enum_extensions([])
    assert extensions == {
        "ExpectedBehavior": set(),
        "ArtifactKind": set(),
        "PrimaryIssue": set(),
    }


# -----------------------------------------------------------------------------
# main() delegation + _read_artifact_validation_notes empty-file branch
# -----------------------------------------------------------------------------

def test_main_invokes_run_stage_c(tmp_path: Path) -> None:
    """`main(argv)` parses args and delegates to `run_stage_c`; the exit code
    of `run_stage_c` propagates back as `main`'s return value. Also pins the
    `load_dotenv(<repo>/.env, override=False)` call so a regression of the
    "GCP_API_KEY in .env but not in shell env" failure mode (see commit
    `243f256`) is caught here, not only by live tests.
    """
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"
    fei_csv = tmp_path / "fei.csv"
    av_csv = tmp_path / "av.csv"
    fei_csv.touch()
    av_csv.touch()

    with (
        patch("tools.e2e.functional_evaluator.load_dotenv") as mock_load_dotenv,
        patch(
            "tools.e2e.functional_evaluator.run_stage_c",
            MagicMock(return_value=0),
        ) as mock_run,
    ):
        rc = main([
            "--fei-csv", str(fei_csv),
            "--av-csv", str(av_csv),
            "--out-usefulness", str(fu_csv),
            "--out-sidecar", str(sidecar_csv),
            "--max-parallel-queries", "2",
            "--allow-partial-stage-c",
        ])
    assert rc == 0
    assert mock_run.call_count == 1
    # Verify delegation surface: kwargs flow through to `run_stage_c`.
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["fei_csv_path"] == fei_csv
    assert call_kwargs["artifact_csv_path"] == av_csv
    assert call_kwargs["out_usefulness_csv"] == fu_csv
    assert call_kwargs["out_sidecar_csv"] == sidecar_csv
    assert call_kwargs["max_parallel_queries"] == 2
    assert call_kwargs["allow_partial"] is True
    # NEW-2 pin: `main()` must call `load_dotenv(<repo>/.env, override=False)`
    # before delegating to run_stage_c, otherwise live Stage C will reject every
    # query when GCP_API_KEY is in .env but not in shell env (commit 243f256).
    assert mock_load_dotenv.call_count == 1
    load_args, load_kwargs = mock_load_dotenv.call_args
    assert str(load_args[0]).endswith(".env"), (
        f"load_dotenv called with non-.env path: {load_args[0]!r}"
    )
    assert load_kwargs.get("override") is False, (
        "override=False is load-bearing: shell-set GCP_API_KEY must win over .env"
    )


def test_read_artifact_validation_notes_returns_empty_when_file_absent(
    tmp_path: Path,
) -> None:
    """When the artifact CSV does not exist on disk, the helper returns an
    empty dict (covers the `if not av_csv_path.is_file()` branch).
    """
    from tools.e2e.functional_evaluator import _read_artifact_validation_notes

    missing = tmp_path / "definitely-not-here.csv"
    assert not missing.exists()
    assert _read_artifact_validation_notes(missing) == {}
