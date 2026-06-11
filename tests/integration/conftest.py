"""Fixtures shared by the T12 sidecar compose-E2E + containment suite.

Scoped narrowly (no autouse) so the rest of tests/integration is unaffected.
"""
from __future__ import annotations

import os

import pytest

from tests.harness.containers import docker_available
from tests.integration import _sidecar_e2e_helpers as H


@pytest.fixture(autouse=True)
def _allow_docker_unix_socket(request) -> None:
    """Re-arm docker-py's Unix-socket access for live_docker tests.

    pytest-socket's `--disable-socket` re-blocks sockets around every test, which
    breaks `docker.from_env()` inside the production start_container path. The repo's
    existing live tests re-enable the Unix socket in-test; we do the same, scoped to
    live_docker-marked tests so non-docker integration tests keep their isolation."""
    if request.node.get_closest_marker("live_docker"):
        from tests.harness.containers import _allow_docker_unix_socket_only
        _allow_docker_unix_socket_only()
    yield


@pytest.fixture(scope="session")
def ns_creds() -> tuple[str, str]:
    """(api_user, api_pass) for the local NExtSEEK stack; skip if .env is absent."""
    user, password = H.ns_credentials()
    if not user or not password:
        pytest.skip("NEXTSEEK_USERNAME/PASSWORD not in .env; live sidecar tests need them")
    return user, password


@pytest.fixture(scope="session")
def sidecar_up_session() -> None:
    """Bring the sidecar compose stack up around the live_docker session (R-6).

    Session-scoped: one up/down for the whole run rather than per test. The bring-up
    is idempotent (`make sidecar-up` uses `--wait`), so it is a no-op if the operator
    already started it via the task's run command."""
    # xdist race guard: this fixture is session-scoped, but pytest-xdist gives each
    # worker its OWN session, so N workers would each fire `make sidecar-up`/`-down`
    # concurrently — tearing the shared sidecar out from under sibling workers
    # mid-test. The live_docker suite MUST run single-process; tell the operator how.
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail(
            "live_docker sidecar tests cannot run under pytest-xdist (each worker "
            "would up/down the shared sidecar concurrently). Re-run with `-p no:xdist`."
        )
    if not docker_available():
        pytest.skip("docker daemon not available")
    H.sidecar_up()
    try:
        yield
    finally:
        H.sidecar_down()
