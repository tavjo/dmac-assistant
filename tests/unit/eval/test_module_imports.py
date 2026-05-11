"""T01: package skeleton + image-side eval-group import smoke test.

This test is the contract for task-01-scaffold-and-deps. It MUST fail before
the package skeleton is created AND the `hibayes-runtime-reliability:dev`
image is built, and MUST pass when invoked inside that image.

**Host-vs-image execution**. This file is intended to run inside the
`hibayes-runtime-reliability:dev` container. The host bridge venv does NOT
carry the eval-group dependencies; if pytest is invoked on the host without
the image, every test except `test_dmac_assistant_eval_package_imports`
should SKIP cleanly (not error). The module-level `pytest.importorskip`
on `hibayes` achieves this — without it, the parametrized import test would
raise a collection-time ImportError on the host.
"""
from __future__ import annotations

import importlib

import pytest

# Skip every test in this module on hosts that lack `hibayes` (i.e. anywhere
# but inside the dmac-assistant eval image). This keeps the host bridge
# pytest suite green without ignoring this directory in pytest config.
pytest.importorskip(
    "hibayes",
    reason="eval-group dependency; this test file only runs inside the "
           "hibayes-runtime-reliability:dev image. On the host bridge venv, "
           "skip cleanly.",
)


def test_dmac_assistant_eval_package_imports() -> None:
    """The new package + subpackage must be importable as Python modules."""
    eval_pkg = importlib.import_module("dmac_assistant.eval")
    assert hasattr(eval_pkg, "__path__"), (
        "dmac_assistant.eval must be a package, not a module"
    )
    sub = importlib.import_module(
        "dmac_assistant.eval.hibayes_runtime_reliability"
    )
    assert hasattr(sub, "__path__"), (
        "hibayes_runtime_reliability must be a package, not a module"
    )


@pytest.mark.parametrize(
    "module_name",
    ["hibayes", "numpyro", "arviz", "jinja2", "matplotlib"],
)
def test_eval_group_dependency_imports(module_name: str) -> None:
    """Every dependency in the eval group must import cleanly inside the image."""
    importlib.import_module(module_name)


def test_hibayes_two_level_group_binomial_resolves() -> None:
    """OQ-1 / Phase 2C Q1: HiBayes ships `two_level_group_binomial`.

    Pins T05's integration surface. If the model builder moves or is renamed
    upstream, T01 catches it before T05.
    """
    from hibayes.model.models import two_level_group_binomial

    assert callable(two_level_group_binomial), (
        "two_level_group_binomial must be a callable model builder"
    )


def test_hibayes_model_analysis_state_resolves() -> None:
    """DL-006 / DD-05: T05 constructs `ModelAnalysisState` directly.

    Pin the import surface here.
    """
    from hibayes.analysis_state import ModelAnalysisState

    assert isinstance(ModelAnalysisState, type), (
        "ModelAnalysisState must be a class importable from hibayes.analysis_state"
    )
