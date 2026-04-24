"""T01 bootstrap tests: package importable, FastAPI app object exists, /health works."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _example_value(name: str, contents: str) -> str:
    for line in contents.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{name} not found in .env.example")


@pytest.fixture
def allow_unix_socket_only():
    """Permit local socketpair usage for the test; restore the strict default on teardown.

    The repo-wide `--disable-socket` default in `pyproject.toml` blocks every socket
    family, including `AF_UNIX`. FastAPI's `TestClient` uses a socketpair under the
    hood, so bridge unit tests need `AF_UNIX` allowed for the duration of the test
    body only. Teardown re-asserts the strict default so no later test in the same
    worker inherits a relaxed state.
    """
    try:
        import pytest_socket
    except ImportError:
        yield
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


def test_dmac_assistant_package_is_importable() -> None:
    """T02-T06 all assume `import dmac_assistant.X`. This proves it resolves."""
    import dmac_assistant  # noqa: F401

    assert dmac_assistant.__name__ == "dmac_assistant"


def test_app_module_exposes_fastapi_app_object() -> None:
    """DD-01: `uvicorn dmac_assistant.app:app` is the canonical launch command."""
    from fastapi import FastAPI

    from dmac_assistant.app import app

    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_ok(allow_unix_socket_only) -> None:
    """/health is the one endpoint T01 ships. Shape is fixed: {"status": "ok"}."""
    from fastapi.testclient import TestClient

    from dmac_assistant.app import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_t06_app_exposes_health_login_and_ws_chat() -> None:
    """After T06, the bridge exposes /health, /auth/login, and /ws/chat."""
    from dmac_assistant.app import app

    user_paths = {
        route.path for route in app.routes if getattr(route, "path", "").startswith("/")
    }
    framework_defaults = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    app_routes = user_paths - framework_defaults

    required = {"/health", "/auth/login", "/ws/chat"}
    assert required.issubset(app_routes), (
        f"post-T06 app must expose /health, /auth/login, and /ws/chat; "
        f"found {app_routes}."
    )


def test_env_example_includes_bridge_bootstrap_variables() -> None:
    """Wave 1 owns the bridge bootstrap env contract, not only T02's loader."""
    contents = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert json.loads(_example_value("DMAC_USERS", contents)) == {
        "alice": {
            "password": "dev-only-replace-me",
            "projects": ["example-project"],
        }
    }
    assert _example_value("DMAC_BRIDGE_HOST", contents) == "127.0.0.1"
    assert _example_value("DMAC_BRIDGE_PORT", contents) == "8000"


@pytest.mark.live_bridge
def test_live_bridge_marker_is_registered() -> None:
    """Collection should accept the marker without requiring Docker."""
    assert True
