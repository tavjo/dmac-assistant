"""T04: aggregator behavioral contract.

Loads the canonical fixture, asserts EVERY field of EVERY aggregate matches the
hand-computed JSON exactly, plus the four edge fixtures and four helper-level
tests added in REFACTOR (Step 5 in §4).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from dmac_assistant.eval.hibayes_runtime_reliability.load_csv import load_runtime_eval_csv
from dmac_assistant.eval.hibayes_runtime_reliability.models import (
    RuntimeEvalRow,
    TaskFamilyAggregate,
)
from dmac_assistant.eval.hibayes_runtime_reliability.process_runtime_reliability import (
    GlobalTotals,
    _avg_cost_usd_none_aware,
    _avg_field,
    _count_artifact_rows,
    _count_failure_modes,
    aggregate_by_task_family,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "hibayes_runtime_reliability"


def _aggregate_by_name(aggs: list[TaskFamilyAggregate], name: str) -> TaskFamilyAggregate:
    matches = [a for a in aggs if a.task_family == name]
    assert len(matches) == 1, f"expected exactly one '{name}' aggregate, got {len(matches)}"
    return matches[0]


def _close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=0, abs_tol=tol)


# --- Canonical fixture: every aggregate field matches the hand-computed JSON --------

def test_aggregator_matches_hand_computed_json_exactly() -> None:
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    aggs, totals = aggregate_by_task_family(rows)
    expected = json.loads(
        (FIXTURES / "tiny_three_family_expected_aggregates.json").read_text()
    )

    assert len(aggs) == len(expected["aggregates"])
    for exp_agg in expected["aggregates"]:
        actual = _aggregate_by_name(aggs, exp_agg["task_family"])
        for field in (
            "n_total", "n_success", "n_failure", "n_error", "n_timeout",
            "n_no_answer", "n_artifact_rows",
        ):
            assert getattr(actual, field) == exp_agg[field], (
                f"{exp_agg['task_family']}.{field}: "
                f"actual={getattr(actual, field)} expected={exp_agg[field]}"
            )
        for field in (
            "observed_success_rate", "avg_latency_seconds", "avg_cost_usd",
            "avg_tool_calls_total",
        ):
            assert _close(getattr(actual, field), exp_agg[field]), (
                f"{exp_agg['task_family']}.{field}: "
                f"actual={getattr(actual, field)} expected={exp_agg[field]}"
            )

    # Totals
    exp_totals = expected["totals"]
    assert isinstance(totals, GlobalTotals)
    assert totals.n_total == exp_totals["n_total"]
    assert totals.n_success == exp_totals["n_success"]
    assert totals.n_failure == exp_totals["n_failure"]
    assert _close(totals.observed_success_rate, exp_totals["observed_success_rate"])
    assert totals.n_families == exp_totals["n_families"]


# --- Edge fixtures (R-04, R-05, R-09, DD-11) ----------------------------------------

def test_aggregator_handles_single_row_family() -> None:
    """R-04 forward-pointer: 1-row family produces n_total=1 without crash; T05 will band it."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "edge_single_row_family.csv")
    aggs, totals = aggregate_by_task_family(rows)
    assert len(aggs) == 1
    a = aggs[0]
    assert a.n_total == 1 and a.n_success == 1 and a.n_failure == 0
    assert a.observed_success_rate == 1.0
    assert totals.n_families == 1


def test_aggregator_emits_none_for_all_none_cost_family() -> None:
    """R-05: avg_cost_usd is None when every row in the family has cost_usd=None."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "edge_all_none_cost.csv")
    aggs, _totals = aggregate_by_task_family(rows)
    assert len(aggs) == 1
    assert aggs[0].avg_cost_usd is None


def test_aggregator_collapses_normalized_families() -> None:
    """R-09: rows with mixed casing/whitespace fold into one normalized family."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "edge_normalization.csv")
    aggs, totals = aggregate_by_task_family(rows)
    by_name = {a.task_family: a for a in aggs}
    assert set(by_name) == {"search-basic", "other-family"}
    assert by_name["search-basic"].n_total == 3   # three normalized rows merged
    assert by_name["other-family"].n_total == 1
    assert totals.n_families == 2


def test_aggregate_has_no_is_opus_field_at_runtime() -> None:
    """DD-11: structural runtime check (T03 enforces at model-fields level; this is the
    instance-level check on a real fixture pass)."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "edge_sonnet_only.csv")
    aggs, _totals = aggregate_by_task_family(rows)
    assert len(aggs) == 1
    assert not hasattr(aggs[0], "is_opus")
    # Rows still carry is_opus
    assert all(r.is_opus == 0 for r in rows)


# --- Helper-level tests (REFACTOR Step 5) -------------------------------------------

def _row(**overrides) -> RuntimeEvalRow:
    base = {
        "query_id": "x", "task_family": "f", "task_subtype": None, "image": "img",
        "answer_provided": True, "is_error": False, "timed_out": False,
        "runtime_success": True, "failure_mode": "none",
        "latency_seconds": 1.0, "cost_usd": 0.01,
        "tool_calls_total": 1, "artifact_count": 0, "is_opus": 1,
    }
    base.update(overrides)
    return RuntimeEvalRow.model_validate(base)


def test_count_failure_modes_helper() -> None:
    rows = [
        _row(answer_provided=False, is_error=True, runtime_success=False, failure_mode="error"),
        _row(answer_provided=False, timed_out=True, runtime_success=False, failure_mode="timeout"),
        _row(answer_provided=False, runtime_success=False, failure_mode="no_answer"),
        _row(),  # success
    ]
    n_error, n_timeout, n_no_answer = _count_failure_modes(rows)
    assert (n_error, n_timeout, n_no_answer) == (1, 1, 1)


def test_avg_cost_usd_none_aware_helper() -> None:
    assert _avg_cost_usd_none_aware([_row(cost_usd=None), _row(cost_usd=None)]) is None
    avg = _avg_cost_usd_none_aware([_row(cost_usd=None), _row(cost_usd=0.10)])
    assert avg == 0.10  # mean of non-None values only


def test_avg_field_helper() -> None:
    rows = [_row(latency_seconds=1.0), _row(latency_seconds=3.0)]
    assert _avg_field(rows, "latency_seconds") == 2.0


def test_count_artifact_rows_helper() -> None:
    rows = [_row(artifact_count=0), _row(artifact_count=1), _row(artifact_count=5)]
    assert _count_artifact_rows(rows) == 2  # only the rows with artifact_count > 0


# --- GlobalTotals negative path (closes coverage gate on the validator's raise branch) -

def test_global_totals_rejects_inconsistent_counts() -> None:
    """N-1 closure: validator added on GlobalTotals must reject n_total != n_success+n_failure."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GlobalTotals(
            n_total=5, n_success=3, n_failure=1,  # 3+1 != 5
            observed_success_rate=0.6, n_families=1,
        )
