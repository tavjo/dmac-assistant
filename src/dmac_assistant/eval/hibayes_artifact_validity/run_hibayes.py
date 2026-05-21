"""T3.1 — Stage D in-image entry point for the artifact-validity axis.

Per locked DD-40: fits `two_level_group_binomial`; emits posterior.json matching
locked DD-41's nested wrapper schema verbatim.

DD-42: imports `hibayes` here at MODULE level (NOT in models.py and NOT in
function scope — module-level imports are load-bearing for the DL-028
wrapper-smoke contract, which requires `--help` to exercise the hibayes import
path).

API surface mirrored verbatim from the existing runtime axis at
`src/dmac_assistant/eval/hibayes_runtime_reliability/run_hibayes.py:33-42,
83-93, 128-153, 180-224`:
  - `ModelAnalysisState`, `ModelConfig`, `FitConfig`, `PlatformConfig`,
    module-level `fit as _hibayes_fit`, `two_level_group_binomial` —
    the typed HiBayes 1.0.0 API.
  - `_build_features` returns `{"obs", "num_group", "group_index", "n_total"}`
    (the locked DD-05 Features dict shape; identical to the runtime axis).
  - Posterior extraction via ArviZ on `idata.posterior["group_effects"]` with
    sigmoid transform, NOT via fictional `posterior.posterior_mean(group=i)` /
    `posterior.hdi_94(...)` / `posterior.p_lt(...)` methods.
"""
from __future__ import annotations

# isort:skip_file -- import order is load-bearing for matplotlib backend (R-07
# in the existing runtime axis); enforced here for parity.
import matplotlib  # isort:skip
matplotlib.use("Agg")  # isort:skip  -- BEFORE any pyplot import.

import argparse
import importlib.resources
import json
import sys
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np
import yaml

# DL-028 contract: module-level hibayes imports — `--help` MUST exercise this
# import path. Function-scoped imports would short-circuit on `--help` and
# defeat the smoke gate (see plan DL-028 + this spec's D3 fix-log).
from hibayes.analysis_state import ModelAnalysisState
from hibayes.model import ModelConfig, fit as _hibayes_fit, two_level_group_binomial
from hibayes.model.model_config import FitConfig
from hibayes.platform import PlatformConfig

from .load_csv import load_artifact_validity_csv
from .models import PosteriorTaskFamilyReliability
from .process import TaskFamilyArtifactAggregate, aggregate_by_task_family

# DL-028 + locked DD-28: module-level config resource. `importlib.resources`
# resolves this against the installed package, so `--help` triggers per-axis
# YAML ModelConfig discovery via argparse default-value computation below.
_DEFAULT_CONFIG_RESOURCE = (
    "dmac_assistant.eval.hibayes_artifact_validity",
    "config/hibayes_artifact_validity.yaml",
)


def _discover_default_config_path() -> Path:
    """Return the packaged-YAML path; computed at import / argparse-default time.

    Called twice: once at module import for the argparse `default=` value (so
    `--help` exercises the discovery path per DL-028 sub-condition (c)), and
    again at runtime if the user does NOT pass `--config`. Side-effect-free.
    """
    pkg, rel = _DEFAULT_CONFIG_RESOURCE
    return Path(importlib.resources.files(pkg) / rel)


# DL-028 sub-condition (c): force per-axis YAML ModelConfig discovery at
# import time. `--help` reaches this line before argparse runs.
_DEFAULT_CONFIG_PATH: Path = _discover_default_config_path()


def _build_features(
    aggregates: list[TaskFamilyArtifactAggregate],
) -> dict[str, Any]:
    """DD-05-style Features dict — mirrors existing runtime axis verbatim.

    Shape: ``{"obs", "num_group", "group_index", "n_total"}``. The HiBayes
    1.0.0 `two_level_group_binomial` model builder consumes exactly these keys
    (see `src/dmac_assistant/eval/hibayes_runtime_reliability/run_hibayes.py:83-93`).
    Do NOT introduce a `"group"` key — that key shape is fictional and would
    fail the model's NumPyro plate construction at runtime.
    """
    n_total = np.asarray([a.n_total for a in aggregates], dtype=np.int32)
    obs = np.asarray([a.n_success for a in aggregates], dtype=np.int32)
    group_index = np.arange(len(aggregates), dtype=np.int32)
    return {
        "obs": obs,
        "num_group": int(len(aggregates)),
        "group_index": group_index,
        "n_total": n_total,
    }


def _band(
    posterior_mean: float,
    p_lt_strong: float,
    p_lt_acceptable: float,
    n_total: int,
) -> str:
    """Banding logic — returns a string per locked DD-41 (`band: str` in the
    posterior.json schema). Mirrors the runtime axis's banding categories
    verbatim (`Reliable`, `Watch`, `Brittle`, `TooUncertain`). Cross-axis
    enum-vs-str note: the runtime axis's `PosteriorTaskFamilyReliability.band`
    is a `ReliabilityBand` enum and writes `p.band.value` (a string) to CSV at
    `run_hibayes.py:329`; the artifact axis emits posterior.json directly with
    a `str`, so no `.value` extraction is needed here. See Implementation Notes.
    """
    if n_total < 3:
        return "TooUncertain"
    if posterior_mean >= 0.95 and p_lt_strong < 0.20:
        return "Reliable"
    if p_lt_acceptable >= 0.50:
        return "Brittle"
    if posterior_mean >= 0.80 and p_lt_acceptable < 0.30:
        return "Watch"
    return "TooUncertain"


def _fit_two_level_group_binomial(
    aggregates: list[TaskFamilyArtifactAggregate],
    *,
    prior_sigma_group_scale: float,
    thresholds: dict[str, float],
    seed: int,
) -> list[PosteriorTaskFamilyReliability]:
    """Per locked DD-40: fit `two_level_group_binomial`; extract posteriors
    via ArviZ on `idata.posterior["group_effects"]` + sigmoid (mirroring the
    runtime axis at `run_hibayes.py:156-224` verbatim).

    Sampler-knob translation (matches existing axis lines 75-80 + 128-152):
      warmup=500, samples=1000, chains=2, chain_method="sequential",
      prior_sigma_group_scale tuned per locked DD-40 methodology.
    """
    if not aggregates:
        return []

    features = _build_features(aggregates)
    model_builder = two_level_group_binomial(
        prior_sigma_group_scale=prior_sigma_group_scale,
    )
    coords = {"group": list(range(features["num_group"]))}
    dims = {"obs": ["group"], "n_total": ["group"], "group_index": ["group"]}
    state = ModelAnalysisState(
        model=model_builder,
        model_config=ModelConfig(
            fit=FitConfig(warmup=500, samples=1000, chains=2, seed=seed),
        ),
        platform_config=PlatformConfig(chain_method="sequential"),
        features=features,
        test_features=None,
        coords=coords,
        dims=dims,
        inference_data=None,
        diagnostics={},
        is_fitted=False,
    )
    _hibayes_fit(state)  # mutates state in-place; returns None.

    # ArviZ posterior extraction — mirror runtime axis lines 180-198.
    idata = state.inference_data
    group_effects = idata.posterior["group_effects"]
    theta_local = 1.0 / (1.0 + np.exp(-group_effects))
    means = theta_local.mean(dim=("chain", "draw")).values
    medians = theta_local.median(dim=("chain", "draw")).values
    _ge_hdi95 = az.hdi(
        idata, hdi_prob=0.95, var_names=["group_effects"]
    )["group_effects"]
    hdi95_lower = 1.0 / (1.0 + np.exp(-_ge_hdi95.sel(hdi="lower").values))
    hdi95_higher = 1.0 / (1.0 + np.exp(-_ge_hdi95.sel(hdi="higher").values))
    strong = float(thresholds.get("strong", 0.9))
    acceptable = float(thresholds.get("acceptable", 0.8))
    p_lt_strong = (theta_local < strong).mean(dim=("chain", "draw")).values
    p_lt_acceptable = (theta_local < acceptable).mean(dim=("chain", "draw")).values

    results: list[PosteriorTaskFamilyReliability] = []
    for i, agg in enumerate(aggregates):
        mean_i = float(means[i])
        median_i = float(medians[i])
        p_lt_strong_i = float(p_lt_strong[i])
        p_lt_acceptable_i = float(p_lt_acceptable[i])
        band = _band(mean_i, p_lt_strong_i, p_lt_acceptable_i, agg.n_total)
        results.append(
            PosteriorTaskFamilyReliability(
                task_family=agg.task_family,
                n_total=agg.n_total,
                posterior_mean=mean_i,
                posterior_median=median_i,
                hdi_low=float(hdi95_lower[i]),
                hdi_high=float(hdi95_higher[i]),
                p_success_lt_strong=p_lt_strong_i,
                p_success_lt_acceptable=p_lt_acceptable_i,
                band=band,  # str per locked DD-41 + models.py
            )
        )
    return results


def write_posterior_json(
    *,
    out_path: Path,
    axis: str,
    model: str,
    prior_sigma_group_scale: float,
    strata: list[PosteriorTaskFamilyReliability],
    metadata: dict[str, Any],
) -> None:
    """Emit posterior.json with locked DD-41 nested wrapper schema (5 top-level keys)."""
    payload = {
        "axis": axis,
        "model": model,
        "prior_sigma_group_scale": prior_sigma_group_scale,
        "strata": [s.model_dump(mode="json") for s in strata],
        "metadata": metadata,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_artifact_axis(
    *,
    input_csv: Path,
    out_dir: Path,
    thresholds: dict[str, float],
    prior_sigma_group_scale: float,
    seed: int,
) -> Path:
    """Run the artifact-validity axis end-to-end. Returns the posterior.json path."""
    rows = load_artifact_validity_csv(input_csv)
    aggregates = aggregate_by_task_family(rows)
    strata = _fit_two_level_group_binomial(
        aggregates,
        prior_sigma_group_scale=prior_sigma_group_scale,
        thresholds=thresholds,
        seed=seed,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    posterior_path = out_dir / "posterior.json"
    write_posterior_json(
        out_path=posterior_path,
        axis="artifact",
        model="two_level_group_binomial",
        prior_sigma_group_scale=prior_sigma_group_scale,
        strata=strata,
        metadata={
            "run_id": input_csv.stem,
            "axis_input_csv": str(input_csv),
            "thresholds": thresholds,
            "fit_diagnostics": {},
        },
    )
    return posterior_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmac_assistant.eval.hibayes_artifact_validity.run_hibayes",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/work/out/hibayes_artifact_validity"),
    )
    # Default resolves at MODULE-import time (see `_DEFAULT_CONFIG_PATH`) so
    # `--help` exercises the per-axis YAML discovery path per DL-028 (c).
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG_PATH,
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    cfg: dict[str, Any] = {}
    if args.config.is_file():
        cfg = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    thresholds = {
        "strong": float(cfg.get("strong_floor", 0.9)),
        "acceptable": float(cfg.get("acceptable_floor", 0.8)),
    }
    sigma = float(cfg.get("prior_sigma_group_scale", 2.0))
    run_artifact_axis(
        input_csv=args.input,
        out_dir=args.out_dir,
        thresholds=thresholds,
        prior_sigma_group_scale=sigma,
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
