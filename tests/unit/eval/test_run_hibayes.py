"""T05 - HiBayes integration: end-to-end fit + posterior + ordering tests."""
from __future__ import annotations

import csv
import pytest
from pathlib import Path

# Host venv lacks the eval group per DD-13 / Amendment 1. Skip this entire
# module on hosts without hibayes so `uv run pytest -q` stays green when the
# in-container test run is the authoritative gate. Inside the image all
# tests collect and run.
pytest.importorskip("hibayes")

import matplotlib  # noqa: E402  (after importorskip)

from dmac_assistant.eval.hibayes_runtime_reliability.load_csv import load_runtime_eval_csv  # noqa: E402
from dmac_assistant.eval.hibayes_runtime_reliability.models import (  # noqa: E402
    HiBayesRuntimeReport,
    PosteriorTaskFamilyReliability,
    ReliabilityBand,
    ReliabilityThresholds,
)
from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import run_hibayes  # noqa: E402

FIXTURES = Path(__file__).parents[2] / "fixtures" / "hibayes_runtime_reliability"
SEED = int((FIXTURES / "run_hibayes_seed.txt").read_text().strip())


@pytest.fixture(scope="module")
def fitted_report(tmp_path_factory) -> HiBayesRuntimeReport:
    """Fit once per test module; the same report is read by every test below."""
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    out_dir = tmp_path_factory.mktemp("t05_run_hibayes_out")
    return run_hibayes(rows, ReliabilityThresholds(), out_dir=out_dir, seed=SEED)


def _by_family(posteriors: list[PosteriorTaskFamilyReliability], name: str) -> PosteriorTaskFamilyReliability:
    matches = [p for p in posteriors if p.task_family == name]
    assert len(matches) == 1, f"expected one '{name}' posterior, got {len(matches)}"
    return matches[0]


def test_matplotlib_agg_backend() -> None:
    """R-07: importing run_hibayes must lock the matplotlib backend to 'Agg'.

    This test imports nothing matplotlib-related itself - it only checks the
    side effect of the run_hibayes module-import that pytest already triggered
    via the imports at the top of this file.
    """
    assert matplotlib.get_backend() == "Agg", (
        f"R-07 violation: backend is {matplotlib.get_backend()!r}; "
        "run_hibayes.py must call matplotlib.use('Agg') BEFORE any pyplot import"
    )


def test_brittle_lower_than_reliable(fitted_report: HiBayesRuntimeReport) -> None:
    """RED-list (a): on the 3-family fixture, the brittle group has a meaningfully
    lower posterior_mean than the reliable group. Ordering, not magnitude.
    """
    reliable = _by_family(fitted_report.posteriors, "search-basic")  # 4/4 success
    brittle = _by_family(fitted_report.posteriors, "spreadsheet-tricky")  # 1/4 success
    assert reliable.posterior_mean > brittle.posterior_mean, (
        f"reliable={reliable.posterior_mean!r} not > brittle={brittle.posterior_mean!r}"
    )
    # 'Meaningful' = at least 0.20 - the underlying observed-rate gap is 1.0 - 0.25 = 0.75.
    assert reliable.posterior_mean - brittle.posterior_mean > 0.20


def test_p_lt_80_monotonic(fitted_report: HiBayesRuntimeReport) -> None:
    """RED-list (b): P(success<0.80) is monotonic in the expected direction across families.

    Direction: spreadsheet-tricky (worst) > qaqc-mixed (middle) > search-basic (best).
    """
    reliable = _by_family(fitted_report.posteriors, "search-basic")
    middle = _by_family(fitted_report.posteriors, "qaqc-mixed")
    brittle = _by_family(fitted_report.posteriors, "spreadsheet-tricky")
    assert brittle.p_success_lt_acceptable > middle.p_success_lt_acceptable > reliable.p_success_lt_acceptable, (
        f"non-monotonic: brittle={brittle.p_success_lt_acceptable!r} "
        f"middle={middle.p_success_lt_acceptable!r} reliable={reliable.p_success_lt_acceptable!r}"
    )


def test_band_assignment_uses_thresholds(fitted_report: HiBayesRuntimeReport) -> None:
    """Banding is delegated to ReliabilityThresholds.band_for(...) (T03/DD-06).

    With default thresholds and the 3-family fixture, the brittle family must
    NOT land in Reliable, and the reliable family must NOT land in Brittle.
    Stronger band claims would be sampler-noise dependent; this is the
    minimum-strength assertion that verifies T05 actually consults T03.
    """
    reliable = _by_family(fitted_report.posteriors, "search-basic")
    brittle = _by_family(fitted_report.posteriors, "spreadsheet-tricky")
    assert reliable.band is not ReliabilityBand.Brittle
    assert brittle.band is not ReliabilityBand.Reliable


def test_posterior_csv_columns_in_order(fitted_report: HiBayesRuntimeReport, tmp_path_factory) -> None:
    """Locks the persisted CSV column order AND verifies seed lands in resolved YAML (M-2)."""
    import yaml as _yaml
    # Reuse the report's persistence side effect by resolving the dir from the fixture's tmp.
    # Simpler: re-run into a fresh tmp here so the test is self-contained.
    out_dir = tmp_path_factory.mktemp("t05_csv_columns")
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    run_hibayes(rows, ReliabilityThresholds(), out_dir=out_dir, seed=SEED)
    csv_path = out_dir / "posterior_task_family_reliability.csv"
    assert csv_path.exists()
    with csv_path.open() as fh:
        header = next(csv.reader(fh))
    assert header == [
        "task_family", "n_total", "posterior_mean", "posterior_median",
        "hdi_low", "hdi_high", "p_success_lt_strong",
        "p_success_lt_acceptable", "band",
    ]
    # M-2: seed MUST appear in config.resolved.yaml under sampler.seed so T07
    # can verify reproducibility. The exact value must equal the SEED used.
    resolved_path = out_dir / "config.resolved.yaml"
    assert resolved_path.exists(), "config.resolved.yaml not persisted"
    loaded = _yaml.safe_load(resolved_path.read_text())
    assert "sampler" in loaded, f"sampler key missing: {loaded!r}"
    assert loaded["sampler"].get("seed") == SEED, (
        f"M-2 violation: sampler.seed={loaded['sampler'].get('seed')!r} != SEED={SEED!r}"
    )


def test_extract_posteriors_does_not_mutate_idata(tmp_path_factory) -> None:
    """F-02 regression (2026-05-13): `_extract_posteriors` must NOT inject a
    `theta` DataArray into `idata.posterior`.

    The prior implementation hand-computed `theta = sigmoid(group_effects)` and
    wrote it back into `state.inference_data.posterior`, mutating ArviZ state
    derived from real samples with a derived variable. This silenced the spec
    §6 "loud signal" of a HiBayes variable rename and risked future ArviZ
    consistency-check failures.

    This test runs `run_hibayes` end-to-end on the §8.1 canonical fixture,
    captures the ModelAnalysisState via a spy on `_persist_artifacts` (which
    receives the same `state` reference passed to `_extract_posteriors`), and
    asserts (a) `"theta"` is absent from `idata.posterior.data_vars`,
    (b) `"group_effects"` is still present (the canonical source variable),
    and (c) the §8.1 binding posterior-ordering invariant still holds.
    """
    from unittest.mock import patch

    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh_mod

    captured: dict[str, object] = {}
    real_persist = rh_mod._persist_artifacts

    def _spy_persist(report, state, *, out_dir, seed):
        captured["state"] = state
        return real_persist(report, state, out_dir=out_dir, seed=seed)

    out_dir = tmp_path_factory.mktemp("t05_no_mutation")
    rows, _ = load_runtime_eval_csv(FIXTURES / "tiny_three_family.csv")
    with patch.object(rh_mod, "_persist_artifacts", _spy_persist):
        report = rh_mod.run_hibayes(
            rows, ReliabilityThresholds(), out_dir=out_dir, seed=SEED
        )

    state = captured["state"]
    posterior_vars = set(state.inference_data.posterior.data_vars)
    assert "theta" not in posterior_vars, (
        f"F-02 regression: idata.posterior was mutated; data_vars={posterior_vars!r}"
    )
    assert "group_effects" in posterior_vars, (
        f"canonical source variable missing from posterior: {posterior_vars!r}"
    )
    # §8.1 binding invariant — the no-mutation path still produces the right
    # posterior ordering.
    reliable = _by_family(report.posteriors, "search-basic")
    brittle = _by_family(report.posteriors, "spreadsheet-tricky")
    assert reliable.posterior_mean > brittle.posterior_mean
    assert reliable.posterior_mean - brittle.posterior_mean > 0.20


def test_hdi_80_present_per_family(fitted_report: HiBayesRuntimeReport) -> None:
    """RD-T05-2 / M-1: 80% HDI is surfaced via diagnostics_summary['hdi_80'].

    Asserts the key exists, its keys equal the set of task family names from
    the fitted report's aggregates, and each entry has float `low`/`high`
    bounds with `low < high`. This is the structural lock that prevents an
    executor from shipping a module that never computes 80% HDI (the M-1
    defect from iter-01).
    """
    assert "hdi_80" in fitted_report.diagnostics_summary, (
        "RD-T05-2 violation: diagnostics_summary['hdi_80'] missing"
    )
    hdi_80 = fitted_report.diagnostics_summary["hdi_80"]
    family_names = {a.task_family for a in fitted_report.aggregates}
    assert set(hdi_80.keys()) == family_names, (
        f"hdi_80 family-name mismatch: {set(hdi_80.keys())!r} vs {family_names!r}"
    )
    for fam, bounds in hdi_80.items():
        assert isinstance(bounds, dict), f"{fam}: bounds not a dict ({type(bounds)})"
        assert "low" in bounds and "high" in bounds, f"{fam}: missing low/high keys"
        assert isinstance(bounds["low"], float) and isinstance(bounds["high"], float), (
            f"{fam}: bounds not float ({type(bounds['low'])}, {type(bounds['high'])})"
        )
        assert bounds["low"] < bounds["high"], (
            f"{fam}: degenerate HDI low={bounds['low']!r} high={bounds['high']!r}"
        )
