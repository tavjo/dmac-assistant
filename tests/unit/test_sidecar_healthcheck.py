"""Healthcheck tests (T16): verifies config + NEXTSEEK_BASE_URL reachability via /me/ → 401."""
import sys
from types import ModuleType

import pytest


REQUIRED_ENV = {
    "NEXTSEEK_BASE_URL": "http://nextseek_nginx",
    "SIDECAR_STAGING_DIR": "/staging",
}


def _install_fake_httpx(monkeypatch, *, status_code: int = 401, raise_error: bool = False):
    """Install a fake httpx module that returns a stubbed response or raises."""
    fake_httpx = ModuleType("httpx")

    class FakeResponse:
        def __init__(self, sc):
            self.status_code = sc

    class HTTPError(Exception):
        pass

    def get(url, *, timeout=5.0):
        if raise_error:
            raise HTTPError("connection refused")
        return FakeResponse(status_code)

    fake_httpx.get = get
    fake_httpx.HTTPError = HTTPError
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)


def test_healthcheck_ok_on_401(monkeypatch):
    """401 from /me/ = endpoint is up + we're unauthenticated = healthy."""
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    _install_fake_httpx(monkeypatch, status_code=401)
    from sidecar.app import healthcheck
    assert healthcheck.main() == 0


def test_healthcheck_ok_on_200(monkeypatch):
    """200 from /me/ is also healthy (some environments allow unauthenticated health)."""
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    _install_fake_httpx(monkeypatch, status_code=200)
    from sidecar.app import healthcheck
    assert healthcheck.main() == 0


def test_healthcheck_fails_on_connection_error(monkeypatch):
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    _install_fake_httpx(monkeypatch, raise_error=True)
    from sidecar.app import healthcheck
    assert healthcheck.main() == 1


def test_healthcheck_fails_on_unexpected_status(monkeypatch):
    """500 from /me/ = unhealthy."""
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    _install_fake_httpx(monkeypatch, status_code=500)
    from sidecar.app import healthcheck
    assert healthcheck.main() == 1


def test_healthcheck_fails_on_missing_config(monkeypatch):
    for k in REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    from sidecar.app import healthcheck
    assert healthcheck.main() == 1
