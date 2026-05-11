"""T03: Pydantic models + ReliabilityBand classification.

Behavioral contract for `dmac_assistant.eval.hibayes_runtime_reliability.models`.
RED: every assertion below fails before models.py exists; GREEN: all pass after
models.py + the default YAML are shipped.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dmac_assistant.eval.hibayes_runtime_reliability.models import (
    HiBayesRuntimeReport,
    PosteriorTaskFamilyReliability,
    ReliabilityBand,
    ReliabilityThresholds,
    RuntimeEvalRow,
    TaskFamilyAggregate,
)
from tools.hibayes.exporter import FailureMode, HiBayesEvalRow

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "hibayes_runtime_reliability"


def _good_row_payload() -> dict:
    return json.loads((FIXTURE_DIR / "row_valid.json").read_text())


# --- DD-01 / R-08: subclass shape -------------------------------------------------

def test_runtime_eval_row_is_subclass_with_no_new_fields() -> None:
    """RuntimeEvalRow MUST be a HiBayesEvalRow subclass and add zero fields (R-08)."""
    assert issubclass(RuntimeEvalRow, HiBayesEvalRow)
    parent_fields = set(HiBayesEvalRow.model_fields.keys())
    child_fields = set(RuntimeEvalRow.model_fields.keys())
    assert child_fields == parent_fields, (
        f"RuntimeEvalRow added or removed fields vs HiBayesEvalRow: "
        f"added={child_fields - parent_fields}, "
        f"removed={parent_fields - child_fields}"
    )


def test_runtime_eval_row_accepts_known_good_row() -> None:
    """A known-good row constructs cleanly."""
    row = RuntimeEvalRow.model_validate(_good_row_payload())
    assert row.runtime_success is True
    assert row.failure_mode is FailureMode.none
    assert row.is_opus == 1


def test_runtime_eval_row_rejects_inconsistent_runtime_success() -> None:
    """Validator: runtime_success must equal (answer_provided AND not is_error AND not timed_out)."""
    bad = _good_row_payload() | {"runtime_success": False}  # answer_provided=True, no errors → success should be True
    with pytest.raises(ValidationError, match="runtime_success"):
        RuntimeEvalRow.model_validate(bad)


def test_runtime_eval_row_rejects_invalid_is_opus() -> None:
    """Validator: is_opus ∈ {0, 1}."""
    bad = _good_row_payload() | {"is_opus": 2}
    with pytest.raises(ValidationError, match="is_opus"):
        RuntimeEvalRow.model_validate(bad)


def test_runtime_eval_row_rejects_invalid_failure_mode() -> None:
    """Validator: failure_mode ∈ {none, error, timeout, no_answer}.

    Pydantic v2's enum coercion will reject unknown strings before our validator
    fires — that is fine, the contract is "rejects" either way. We assert the
    error mentions the field.
    """
    bad = _good_row_payload() | {"failure_mode": "bogus_mode"}
    with pytest.raises(ValidationError, match="failure_mode"):
        RuntimeEvalRow.model_validate(bad)


# --- DD-11: aggregate / posterior have no is_opus ---------------------------------

def test_aggregate_has_no_is_opus_field() -> None:
    """DD-11: is_opus is preserved on the row but never aggregates into a covariate."""
    assert "is_opus" not in TaskFamilyAggregate.model_fields


def test_posterior_has_no_is_opus_field() -> None:
    """DD-11: is_opus never enters the posterior summary either.

    Also locks the success of `model_rebuild()` at the bottom of models.py: if the
    forward reference `band: ReliabilityBand` failed to resolve, the model would not
    have a `band` field at all (or import would have raised). Asserting `band` IS
    present is the positive companion to the `is_opus` negative.
    """
    assert "is_opus" not in PosteriorTaskFamilyReliability.model_fields
    assert "band" in PosteriorTaskFamilyReliability.model_fields, (
        "model_rebuild() did not resolve the forward reference for `band`"
    )


# --- TaskFamilyAggregate self-consistency -----------------------------------------

def test_task_family_aggregate_validates_n_total_equals_success_plus_failure() -> None:
    """The aggregate enforces n_total = n_success + n_failure (loader-side check duplicated here)."""
    with pytest.raises(ValidationError, match="n_total"):
        TaskFamilyAggregate(
            task_family="search-basic",
            n_total=5,
            n_success=3,
            n_failure=1,  # 3+1=4, not 5 — must reject
            observed_success_rate=0.6,
            n_error=1,
            n_timeout=0,
            n_no_answer=0,
            n_artifact_rows=2,
            avg_latency_seconds=10.0,
            avg_cost_usd=0.05,
            avg_tool_calls_total=3.0,
        )


def test_task_family_aggregate_observed_rate_matches_counts() -> None:
    """observed_success_rate must equal n_success / n_total when n_total > 0."""
    with pytest.raises(ValidationError, match="observed_success_rate"):
        TaskFamilyAggregate(
            task_family="search-basic",
            n_total=4,
            n_success=3,
            n_failure=1,
            observed_success_rate=0.5,  # actual is 0.75 — must reject
            n_error=1, n_timeout=0, n_no_answer=0,
            n_artifact_rows=0,
            avg_latency_seconds=10.0,
            avg_cost_usd=None,
            avg_tool_calls_total=2.0,
        )


def test_task_family_aggregate_accepts_all_none_cost() -> None:
    """avg_cost_usd may be None (R-05 forward-pointer for T04)."""
    agg = TaskFamilyAggregate(
        task_family="search-basic",
        n_total=2, n_success=2, n_failure=0,
        observed_success_rate=1.0,
        n_error=0, n_timeout=0, n_no_answer=0,
        n_artifact_rows=0,
        avg_latency_seconds=5.0,
        avg_cost_usd=None,
        avg_tool_calls_total=1.0,
    )
    assert agg.avg_cost_usd is None


# --- DD-06 + R-04: banding -------------------------------------------------------

@pytest.fixture
def default_thresholds() -> ReliabilityThresholds:
    return ReliabilityThresholds()  # all defaults


@pytest.mark.parametrize(
    "n_total, posterior_mean, p_lt_strong, p_lt_acceptable, expected",
    [
        # Reliable: mean >= 0.95 and P(<0.90) < 0.20.
        (50, 0.97, 0.05, 0.01, ReliabilityBand.Reliable),
        # Watch: not Reliable, mean >= 0.80 and P(<0.80) < 0.30.
        (20, 0.85, 0.40, 0.10, ReliabilityBand.Watch),
        # Brittle: P(<0.80) >= 0.50.
        (10, 0.65, 0.80, 0.55, ReliabilityBand.Brittle),
        # TooUncertain: doesn't qualify for any other band.
        (10, 0.85, 0.40, 0.35, ReliabilityBand.TooUncertain),
    ],
)
def test_band_for_each_band(
    default_thresholds: ReliabilityThresholds,
    n_total: int,
    posterior_mean: float,
    p_lt_strong: float,
    p_lt_acceptable: float,
    expected: ReliabilityBand,
) -> None:
    """All four bands reachable on edge inputs."""
    assert default_thresholds.band_for(
        n_total=n_total,
        posterior_mean=posterior_mean,
        p_lt_strong=p_lt_strong,
        p_lt_acceptable=p_lt_acceptable,
    ) is expected


def test_band_for_forces_too_uncertain_below_min_n(
    default_thresholds: ReliabilityThresholds,
) -> None:
    """R-04: n_total < min_n_for_classification → TooUncertain regardless of mean."""
    assert default_thresholds.min_n_for_classification == 3
    band = default_thresholds.band_for(
        n_total=1,                  # below the floor
        posterior_mean=0.99,        # would otherwise be Reliable
        p_lt_strong=0.001,
        p_lt_acceptable=0.0,
    )
    assert band is ReliabilityBand.TooUncertain


# --- HiBayesRuntimeReport: top-level shape sanity --------------------------------

def test_runtime_report_carries_thresholds_and_aggregates() -> None:
    """The top-level report container holds: aggregates, posteriors, thresholds, run metadata."""
    fields = set(HiBayesRuntimeReport.model_fields.keys())
    required = {"aggregates", "posteriors", "thresholds", "diagnostics_summary", "generated_at"}
    missing = required - fields
    assert not missing, f"HiBayesRuntimeReport missing required fields: {missing}"
