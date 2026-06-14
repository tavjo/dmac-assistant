"""Hermetic unit tests for the NS-target reachability precondition in
``tools/e2e/run_router_e2e.py``.

Root cause captured 2026-06-11: ``_agent_nextseek_url()`` falls back to ``.env``'s
``NEXTSEEK_URL`` (the dev server) when ``DMAC_E2E_NS_URL`` is unset, and passes a
non-local host through unchanged. If that server is unreachable, every NS-route
query's POST transport-fails and surfaces as ``ns_query_complete_with_error``
(``status:"error"``) — a failure that masquerades as a NExtSEEK *pipeline* error.
``_check_ns_target_reachable`` makes the harness fail fast and loud instead, with a
remedy that names ``DMAC_E2E_NS_URL``. See
``.claude/reports/2026-06-11-ns-error-root-cause-harness-targets-dead-dev-server.md``.
"""
from __future__ import annotations

import httpx
import pytest

import tools.e2e.run_router_e2e as rr


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _ReachableClient:
    """Stub httpx.Client whose GET returns a response (server is alive)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.requested: list[str] = []

    def __enter__(self) -> "_ReachableClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        self.requested.append(url)
        return _FakeResponse(404)


class _UnreachableClient:
    """Stub httpx.Client whose GET raises a transport error (server is dead)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_UnreachableClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        raise httpx.ConnectTimeout("timed out")


@pytest.fixture(autouse=True)
def _clear_ns_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DMAC_E2E_NS_URL", raising=False)
    monkeypatch.setenv("NEXTSEEK_URL", "https://nextseek-dev.mit.edu")


def test_reachable_target_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live server (any HTTP status, incl. 404/401) is a pass."""
    monkeypatch.setenv("DMAC_E2E_NS_URL", "http://localhost:8000")
    monkeypatch.setattr(rr.httpx, "Client", _ReachableClient)
    assert rr._check_ns_target_reachable(None) is None


def test_unreachable_dev_server_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact footgun: DMAC_E2E_NS_URL unset -> dev server -> dead -> error string."""
    monkeypatch.setattr(rr.httpx, "Client", _UnreachableClient)
    problem = rr._check_ns_target_reachable(None)
    assert problem is not None
    # Names the resolved target and the remedy env var so the operator can act.
    assert "nextseek-dev.mit.edu" in problem
    assert "DMAC_E2E_NS_URL" in problem


def test_host_gateway_is_probed_via_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent URL uses host.docker.internal, which the HOST can't resolve;
    the precheck must probe localhost:<port> instead (same published port)."""
    monkeypatch.setenv("DMAC_E2E_NS_URL", "http://localhost:8000")
    captured = _ReachableClient()
    monkeypatch.setattr(rr.httpx, "Client", lambda *a, **k: captured)
    assert rr._check_ns_target_reachable(None) is None
    assert captured.requested, "precheck issued no probe request"
    probed = captured.requested[0]
    # Agent target translates localhost -> host.docker.internal; the host probe
    # must translate it back to localhost (never probe host.docker.internal, which
    # is unresolvable from the host process).
    assert "host.docker.internal" not in probed
    assert "localhost:8000" in probed


def test_skips_when_no_ns_discriminator_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--ids selecting only container_cc/unrelated queries makes the NS target
    irrelevant; the precheck must not block (and must not even probe)."""
    def _boom(*a: object, **k: object) -> None:  # pragma: no cover - must not run
        raise AssertionError("precheck probed despite no NS discriminator selected")

    monkeypatch.setattr(rr.httpx, "Client", _boom)
    assert rr._check_ns_target_reachable(frozenset({"Unrelated-1"})) is None


def test_ns_subset_selected_still_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """An --ids subset that includes an NS discriminator still triggers the probe."""
    monkeypatch.setattr(rr.httpx, "Client", _UnreachableClient)
    problem = rr._check_ns_target_reachable(frozenset({"Search-Basic-1"}))
    assert problem is not None
