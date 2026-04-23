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


def _allow_unix_socket_only() -> None:
    """Permit local socketpair usage while keeping outbound network disabled."""
    try:
        import pytest_socket
    except ImportError:
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)


def test_dmac_assistant_package_is_importable() -> None:
    """T02-T06 all assume `import dmac_assistant.X`. This proves it resolves."""
    import dmac_assistant  # noqa: F401

    assert dmac_assistant.__name__ == "dmac_assistant"


def test_app_module_exposes_fastapi_app_object() -> None:
    """DD-01: `uvicorn dmac_assistant.app:app` is the canonical launch command."""
    from fastapi import FastAPI

    from dmac_assistant.app import app

    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_ok() -> None:
    """/health is the one endpoint T01 ships. Shape is fixed: {"status": "ok"}."""
    from fastapi.testclient import TestClient

    from dmac_assistant.app import app

    _allow_unix_socket_only()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_is_the_only_route_in_bootstrap() -> None:
    """Guard against later-wave endpoints leaking into the bootstrap task."""
    from dmac_assistant.app import app

    user_paths = {
        route.path for route in app.routes if getattr(route, "path", "").startswith("/")
    }
    framework_defaults = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    app_routes = user_paths - framework_defaults

    assert app_routes == {"/health"}, (
        f"T01 must expose /health only; found {app_routes}. "
        f"Adding endpoints to app.py belongs to a later task."
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
