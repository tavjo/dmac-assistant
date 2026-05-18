"""Pin the `DMAC_E2E_PROJECT` env override for `tools/e2e/run_router_e2e.py`.

Iter-02 Phase 7 residual debt item 4: `SYNTHETIC_PROJECT` was a module-level
string literal (`"proj-a"`) used to populate the synthetic user's project
allowlist and the per-run dropbox state. That worked for the solo-developer
POC where `proj-a` is the canonical allowed project, but multi-user
deployments need a different value without editing the script.

The fix exposes `_synthetic_project()` which reads `DMAC_E2E_PROJECT` from
the environment with `"proj-a"` as the default. These tests pin both halves
of that contract so a future refactor that drops the env-var lookup or
changes the default fails loudly.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def fresh_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Ensure `DMAC_E2E_PROJECT` starts unset for each test."""
    monkeypatch.delenv("DMAC_E2E_PROJECT", raising=False)
    return monkeypatch


def test_synthetic_project_defaults_to_proj_a(fresh_env: pytest.MonkeyPatch) -> None:
    """With no override env var, `_synthetic_project()` returns `proj-a`.

    The default matches the user record provisioned by the synthetic-user
    fixture in `tests/conftest.py` and the bridge project allowlist used
    across the existing E2E manifests.
    """
    from tools.e2e.run_router_e2e import _synthetic_project

    assert _synthetic_project() == "proj-a"


def test_synthetic_project_env_override(fresh_env: pytest.MonkeyPatch) -> None:
    """`DMAC_E2E_PROJECT` overrides the default for non-POC deployments."""
    fresh_env.setenv("DMAC_E2E_PROJECT", "research-lab-42")

    from tools.e2e.run_router_e2e import _synthetic_project

    assert _synthetic_project() == "research-lab-42"


def test_synthetic_project_empty_env_falls_back_to_default(
    fresh_env: pytest.MonkeyPatch,
) -> None:
    """An empty `DMAC_E2E_PROJECT` is treated as unset (falls back to `proj-a`).

    An empty string would otherwise propagate into the user record and the
    dropbox-state mkdir, both of which silently misbehave. Defending against
    operator typos like `DMAC_E2E_PROJECT=` keeps the harness robust.
    """
    fresh_env.setenv("DMAC_E2E_PROJECT", "")

    from tools.e2e.run_router_e2e import _synthetic_project

    assert _synthetic_project() == "proj-a"
