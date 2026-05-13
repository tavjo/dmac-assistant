"""T03: shipped default YAML round-trips through ReliabilityThresholds.

Locks DD-06: thresholds are CONFIG-DRIVEN, not hard-coded. If someone hard-codes
a band threshold in a future task, this test still passes — but the structural
test in test_models.py (parametrized band sweep) will not, because the band
constants would diverge from the YAML defaults.
"""
from __future__ import annotations

import importlib.resources as r

import yaml

from dmac_assistant.eval.hibayes_runtime_reliability.models import ReliabilityThresholds


CONFIG_PKG = "dmac_assistant.eval.hibayes_runtime_reliability.config"
CONFIG_FILE = "hibayes_runtime_reliability.yaml"


def _load_shipped_yaml_text() -> str:
    return (r.files(CONFIG_PKG) / CONFIG_FILE).read_text()


def test_shipped_yaml_loads_into_reliability_thresholds() -> None:
    payload = yaml.safe_load(_load_shipped_yaml_text())
    t = ReliabilityThresholds.model_validate(payload)
    # Round-trip: dumping and re-loading is an identity over the model.
    re_loaded = ReliabilityThresholds.model_validate(t.model_dump())
    assert re_loaded == t


def test_shipped_yaml_defaults_match_dd_06() -> None:
    """Phase 0 lock: the default thresholds in the shipped YAML are exactly DD-06."""
    payload = yaml.safe_load(_load_shipped_yaml_text())
    t = ReliabilityThresholds.model_validate(payload)
    assert t.reliable_mean_floor == 0.95
    assert t.reliable_p_lt_strong_max == 0.20
    assert t.watch_mean_floor == 0.80
    assert t.watch_p_lt_acceptable_max == 0.30
    assert t.brittle_p_lt_acceptable_min == 0.50
    assert t.strong_floor == 0.90
    assert t.acceptable_floor == 0.80
    assert t.min_n_for_classification == 3
