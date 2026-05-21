"""tests/unit/eval/test_posterior_json_adapter.py — pinning tests for T3.3.

Tests the runtime-axis CSV → posterior.json adapter. Adapter is hibayes-import-clean
(stdlib csv/json only) so tests run host-side WITHOUT pytest.importorskip("hibayes").

Locked DD-41 lines 393-417 schema verbatim. plan-DL-024 wrapper-schema pinning.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from dmac_assistant.eval.hibayes_runtime_reliability.posterior_json_adapter import (
    EXPECTED_CSV_HEADER_9,
    adapt_runtime_csv_to_posterior_json,
)


EXPECTED_9_CSV_COLUMNS = [
    "task_family",
    "n_total",
    "posterior_mean",
    "posterior_median",
    "hdi_low",
    "hdi_high",
    "p_success_lt_strong",
    "p_success_lt_acceptable",
    "band",
]


def test_expected_csv_header_9_matches_runtime_axis_emitter() -> None:
    """Pinned to run_hibayes.py:320-323 verbatim 9-column header."""
    assert list(EXPECTED_CSV_HEADER_9) == EXPECTED_9_CSV_COLUMNS


def _write_synthetic_runtime_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EXPECTED_9_CSV_COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def test_adapter_emits_5_top_level_wrapper_keys(tmp_path: Path) -> None:
    """DL-024: posterior.json top-level keys are exactly {axis, model, prior_sigma_group_scale, strata, metadata}."""
    csv_path = tmp_path / "p.csv"
    _write_synthetic_runtime_csv(
        csv_path,
        rows=[
            {
                "task_family": "Search-Basic",
                "n_total": "5",
                "posterior_mean": "0.9",
                "posterior_median": "0.9",
                "hdi_low": "0.7",
                "hdi_high": "0.98",
                "p_success_lt_strong": "0.05",
                "p_success_lt_acceptable": "0.01",
                "band": "Reliable",
            }
        ],
    )
    out = tmp_path / "p.json"
    adapt_runtime_csv_to_posterior_json(
        csv_path=csv_path,
        out_path=out,
        prior_sigma_group_scale=2.0,
        run_id="test-run",
        thresholds={"strong": 0.9, "acceptable": 0.8},
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {
        "axis",
        "model",
        "prior_sigma_group_scale",
        "strata",
        "metadata",
    }


def test_adapter_sets_axis_to_runtime(tmp_path: Path) -> None:
    csv_path = tmp_path / "p.csv"
    _write_synthetic_runtime_csv(csv_path, rows=[])
    out = tmp_path / "p.json"
    adapt_runtime_csv_to_posterior_json(
        csv_path=csv_path,
        out_path=out,
        prior_sigma_group_scale=2.0,
        run_id="t",
        thresholds={"strong": 0.9, "acceptable": 0.8},
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["axis"] == "runtime"
    assert payload["model"] == "two_level_group_binomial"


def test_adapter_per_stratum_9_keys(tmp_path: Path) -> None:
    csv_path = tmp_path / "p.csv"
    _write_synthetic_runtime_csv(
        csv_path,
        rows=[
            {
                "task_family": "Memory",
                "n_total": "3",
                "posterior_mean": "0.7",
                "posterior_median": "0.7",
                "hdi_low": "0.5",
                "hdi_high": "0.9",
                "p_success_lt_strong": "0.2",
                "p_success_lt_acceptable": "0.1",
                "band": "Watch",
            }
        ],
    )
    out = tmp_path / "p.json"
    adapt_runtime_csv_to_posterior_json(
        csv_path=csv_path,
        out_path=out,
        prior_sigma_group_scale=2.0,
        run_id="t",
        thresholds={"strong": 0.9, "acceptable": 0.8},
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["strata"]) == 1
    stratum = payload["strata"][0]
    expected = set(EXPECTED_9_CSV_COLUMNS)
    assert set(stratum.keys()) == expected


def test_adapter_metadata_has_required_subkeys(tmp_path: Path) -> None:
    csv_path = tmp_path / "p.csv"
    _write_synthetic_runtime_csv(csv_path, rows=[])
    out = tmp_path / "p.json"
    adapt_runtime_csv_to_posterior_json(
        csv_path=csv_path,
        out_path=out,
        prior_sigma_group_scale=2.5,
        run_id="abc",
        thresholds={"strong": 0.9, "acceptable": 0.8},
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    md = payload["metadata"]
    assert set(md.keys()) >= {"run_id", "axis_input_csv", "thresholds", "fit_diagnostics"}
    assert md["run_id"] == "abc"
    assert md["thresholds"] == {"strong": 0.9, "acceptable": 0.8}


def test_adapter_keyerrors_loudly_on_diverging_header(tmp_path: Path) -> None:
    """Adapter MUST KeyError if CSV header diverges from the 9-column list."""
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "task_family,n_total,foo\n"
        "Search-Basic,5,extra\n"
    )
    out = tmp_path / "p.json"
    with pytest.raises(KeyError):
        adapt_runtime_csv_to_posterior_json(
            csv_path=csv_path,
            out_path=out,
            prior_sigma_group_scale=2.0,
            run_id="t",
            thresholds={"strong": 0.9, "acceptable": 0.8},
        )


def test_adapter_preserves_numeric_types(tmp_path: Path) -> None:
    """Numeric CSV columns must convert to float/int, NOT remain as strings, in JSON."""
    csv_path = tmp_path / "p.csv"
    _write_synthetic_runtime_csv(
        csv_path,
        rows=[
            {
                "task_family": "Edge",
                "n_total": "6",
                "posterior_mean": "0.95",
                "posterior_median": "0.95",
                "hdi_low": "0.8",
                "hdi_high": "0.99",
                "p_success_lt_strong": "0.02",
                "p_success_lt_acceptable": "0.0",
                "band": "Reliable",
            }
        ],
    )
    out = tmp_path / "p.json"
    adapt_runtime_csv_to_posterior_json(
        csv_path=csv_path,
        out_path=out,
        prior_sigma_group_scale=2.0,
        run_id="t",
        thresholds={"strong": 0.9, "acceptable": 0.8},
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    stratum = payload["strata"][0]
    assert isinstance(stratum["n_total"], int)
    assert isinstance(stratum["posterior_mean"], float)
    assert isinstance(stratum["band"], str)
