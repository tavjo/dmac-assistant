"""T04: CSV loader behavioral contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from dmac_assistant.eval.hibayes_runtime_reliability.load_csv import (
    LoadReport,
    load_runtime_eval_csv,
)
from dmac_assistant.eval.hibayes_runtime_reliability.models import RuntimeEvalRow

FIXTURES = Path(__file__).parents[2] / "fixtures" / "hibayes_runtime_reliability"


def test_loader_accepts_canonical_fixture() -> None:
    rows, report = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    assert len(rows) == 12
    assert report.accepted == 12
    assert report.rejected == []
    assert report.normalized_task_family_count == 0  # all already lowercase
    assert all(isinstance(r, RuntimeEvalRow) for r in rows)


def test_loader_normalizes_task_family(tmp_path: Path) -> None:
    """R-09 / OQ-5: lowercase + strip applied at load time."""
    rows, report = load_runtime_eval_csv(FIXTURES / "edge_normalization.csv")
    assert len(rows) == 4
    families = {r.task_family for r in rows}
    assert families == {"search-basic", "other-family"}, families
    # Three of the four rows had non-canonical form ('Search-Basic', '  SEARCH-BASIC  ').
    assert report.normalized_task_family_count == 2


def test_loader_treats_empty_cost_usd_as_none() -> None:
    """R-05: exporter emits cost_usd='' for None; loader must round-trip to None."""
    rows, report = load_runtime_eval_csv(FIXTURES / "edge_all_none_cost.csv")
    assert len(rows) == 3
    assert all(r.cost_usd is None for r in rows)


def test_loader_records_validation_failures(tmp_path: Path) -> None:
    """If a row violates a T03 validator, it lands in report.rejected, not in rows."""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text(
        "query_id,task_family,task_subtype,image,answer_provided,is_error,timed_out,"
        "runtime_success,failure_mode,latency_seconds,cost_usd,tool_calls_total,"
        "artifact_count,is_opus\n"
        # runtime_success=true but answer_provided=false → T03 validator rejects
        "bad-001,fam,,img,false,false,false,true,none,1.0,0.01,1,0,1\n"
        # Good row alongside it
        "good-001,fam,,img,true,false,false,true,none,1.0,0.01,1,0,1\n"
    )
    rows, report = load_runtime_eval_csv(bad_csv)
    assert len(rows) == 1
    assert rows[0].query_id == "good-001"
    assert len(report.rejected) == 1
    assert report.rejected[0].query_id == "bad-001"
    assert "runtime_success" in report.rejected[0].error


def test_loader_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_runtime_eval_csv(tmp_path / "nope.csv")


def test_loader_preserves_is_opus_per_row() -> None:
    """DD-11: is_opus stays on the row instance verbatim."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    by_id = {r.query_id: r.is_opus for r in rows}
    assert by_id["search-basic-001"] == 1
    assert by_id["search-basic-003"] == 0


def test_load_report_shape() -> None:
    """LoadReport is a small Pydantic-v2-style dataclass; locks its public surface."""
    rows, report = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    assert isinstance(report, LoadReport)
    assert hasattr(report, "accepted")
    assert hasattr(report, "rejected")
    assert hasattr(report, "normalized_task_family_count")
    assert hasattr(report, "warnings")
