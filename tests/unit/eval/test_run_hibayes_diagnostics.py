"""T05 - diagnostic loop + features-dict isolation tests (REFACTOR split)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Host venv lacks the eval group per DD-13 / Amendment 1. Skip this entire
# module on hosts without hibayes; in-container is the authoritative gate.
pytest.importorskip("hibayes")

from dmac_assistant.eval.hibayes_runtime_reliability.load_csv import load_runtime_eval_csv  # noqa: E402
from dmac_assistant.eval.hibayes_runtime_reliability.models import ReliabilityThresholds  # noqa: E402
from dmac_assistant.eval.hibayes_runtime_reliability.process_runtime_reliability import (  # noqa: E402
    aggregate_by_task_family,
)
from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (  # noqa: E402
    DIAGNOSTIC_NAMES,
    _build_features,
    _run_diagnostics,
    run_hibayes,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "hibayes_runtime_reliability"
SEED = int((FIXTURES / "run_hibayes_seed.txt").read_text().strip())

FORBIDDEN_FEATURE_KEYS = {
    "is_opus", "image", "task_subtype", "latency_seconds",
    "cost_usd", "tool_calls_total", "artifact_count",
}


def test_features_dict_shape() -> None:
    """DD-05: Features dict has exactly four keys with the locked names."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    aggregates, _ = aggregate_by_task_family(rows)
    features = _build_features(aggregates)
    assert set(features.keys()) == {"obs", "num_group", "group_index", "n_total"}
    assert isinstance(features["num_group"], int)
    assert features["num_group"] == 3
    assert features["obs"].shape == (3,)
    assert features["n_total"].shape == (3,)
    assert features["group_index"].shape == (3,)
    assert features["obs"].dtype.kind in ("i", "u")  # integer
    assert features["n_total"].dtype.kind in ("i", "u")


def test_is_opus_not_in_features() -> None:
    """DD-11: is_opus and other row-level fields MUST NOT enter the model.

    Pulled from the all-Sonnet edge fixture so a bug that tried to pivot on
    is_opus would have a tempting 'all zeros' input to latch onto.
    """
    rows, _ = load_runtime_eval_csv(FIXTURES / "edge_sonnet_only.csv")
    aggregates, _ = aggregate_by_task_family(rows)
    features = _build_features(aggregates)
    leaked = FORBIDDEN_FEATURE_KEYS & set(features.keys())
    assert not leaked, f"DD-11 violation: model features leaked {leaked!r}"
    # Defense-in-depth: the rows themselves still carry is_opus
    assert all(r.is_opus == 0 for r in rows), "edge fixture changed; expected all is_opus=0"


def test_diagnostics_keys_complete(tmp_path: Path) -> None:
    """RED-list (c): every enumerated diagnostic appears as a key with status in {pass,fail,skip}."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    report = run_hibayes(rows, ReliabilityThresholds(), out_dir=tmp_path, seed=SEED)
    expected_keys = set(DIAGNOSTIC_NAMES)
    assert expected_keys == {
        "r_hat", "divergences", "ess_bulk", "ess_tail",
        "loo", "waic",
        "posterior_predictive_plot", "prior_predictive_plot",
    }, "DIAGNOSTIC_NAMES drifted from the user's spec"
    assert set(report.diagnostics_summary.keys()) >= expected_keys, (
        f"missing diagnostic keys: {expected_keys - set(report.diagnostics_summary.keys())}"
    )
    for name in expected_keys:
        entry = report.diagnostics_summary[name]
        assert "status" in entry and entry["status"] in {"pass", "fail", "skip"}, (
            f"{name}: bad status entry {entry!r}"
        )
        assert "reason" in entry
    # M-3: at least one numeric checker MUST achieve status=='pass' on a valid
    # fitted model. With 1000 draws, chain_method='sequential', the fixed seed,
    # and the 3-family fixture, r_hat / ess_bulk / ess_tail are deterministic
    # and will produce 'pass' under normal conditions. This assertion fails
    # loudly if an executor stubs all diagnostics to 'skip' (the iter-01
    # gameability defect).
    numeric_statuses = {
        name: report.diagnostics_summary[name]["status"]
        for name in ("r_hat", "ess_bulk", "ess_tail")
    }
    assert any(s == "pass" for s in numeric_statuses.values()), (
        f"M-3: no numeric diagnostic achieved status='pass'; "
        f"got {numeric_statuses!r}. This usually means _dispatch_diagnostic "
        "was stubbed (NotImplementedError) instead of wired to "
        "hibayes.check.checkers."
    )


def test_diagnostic_failure_non_fatal(tmp_path: Path) -> None:
    """DD-10: a diagnostic that raises must NOT abort the pipeline; it lands as status=fail."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")

    real_dispatch = None
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as mod
    real_dispatch = mod._dispatch_diagnostic

    def flaky(name: str, state: Any, *, plots_dir: Path) -> None:
        if name == "loo":
            raise RuntimeError("simulated checker failure")
        return real_dispatch(name, state, plots_dir=plots_dir)

    with patch.object(mod, "_dispatch_diagnostic", side_effect=flaky):
        report = run_hibayes(rows, ReliabilityThresholds(), out_dir=tmp_path, seed=SEED)

    # Pipeline did not abort: posteriors exist, report is well-formed.
    assert len(report.posteriors) == 3
    # Failed diagnostic recorded:
    assert report.diagnostics_summary["loo"]["status"] == "fail"
    assert "RuntimeError" in report.diagnostics_summary["loo"]["reason"]
    assert "simulated checker failure" in report.diagnostics_summary["loo"]["reason"]
    # Other diagnostics still ran (at least one is not "fail" with the loo reason):
    other_statuses = {
        name: report.diagnostics_summary[name]["status"]
        for name in DIAGNOSTIC_NAMES if name != "loo"
    }
    assert any(s != "fail" for s in other_statuses.values()), (
        f"all non-loo diagnostics also failed: {other_statuses!r}"
    )
