"""R-03 canary tests for dmac_assistant.router.agent."""
from __future__ import annotations

import logging

import pytest

from dmac_assistant.router.agent import RouterAgent
from dmac_assistant.router.baml_client.types import (
    ModelClass,
    Route,
    RouteCapability,
    TaskFamily,
)


FAKE_CREDENTIAL = "sk-test-canary-fake-secret-do-not-redact-stripping-this-is-a-bug"
CRED_ENV_NAME = "GCP_API_KEY"


@pytest.fixture(autouse=True)
def allow_unix_socket_only():
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


def _minimal_caps() -> list[RouteCapability]:
    return [
        RouteCapability(
            route_name="nextseek_query",
            description="NS.",
            tools=["entity_agent"],
            best_for=None,
            not_for=None,
            task_families=[
                TaskFamily(name="x", description="x", example_queries=["q"])
            ],
        ),
        RouteCapability(
            route_name="container_cc",
            description="CC.",
            tools=["bash"],
            best_for=None,
            not_for=None,
            task_families=[
                TaskFamily(name="y", description="y", example_queries=["q"])
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_caplog_does_not_leak_credentials_on_router_fallback(
    monkeypatch, caplog
):
    leaky_message = f"baml transport failed: {CRED_ENV_NAME}={FAKE_CREDENTIAL}"

    async def leaking_route_query(input):  # noqa: A002
        raise RuntimeError(leaky_message)

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", leaking_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.DEBUG):
        decision = await agent.route("anything")

    assert CRED_ENV_NAME not in caplog.text
    assert FAKE_CREDENTIAL not in caplog.text
    assert decision.route == Route.ContainerCC
    assert decision.model_class == ModelClass.Sonnet
    assert decision.reasoning == "<router_unavailable>"


@pytest.mark.asyncio
async def test_caplog_does_not_leak_credentials_via_exception_args(
    monkeypatch, caplog
):
    async def multi_arg_route_query(input):  # noqa: A002
        raise RuntimeError("first", f"{CRED_ENV_NAME}={FAKE_CREDENTIAL}")

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", multi_arg_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.DEBUG):
        decision = await agent.route("anything")

    assert CRED_ENV_NAME not in caplog.text
    assert FAKE_CREDENTIAL not in caplog.text
    assert decision.reasoning == "<router_unavailable>"


@pytest.mark.asyncio
async def test_caplog_does_not_leak_credentials_via_chained_exception(
    monkeypatch, caplog
):
    async def chained_route_query(input):  # noqa: A002
        inner = ValueError(f"{CRED_ENV_NAME}={FAKE_CREDENTIAL}")
        try:
            raise inner
        except ValueError as exc:
            raise RuntimeError("outer message") from exc

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", chained_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.DEBUG):
        await agent.route("anything")

    assert CRED_ENV_NAME not in caplog.text
    assert FAKE_CREDENTIAL not in caplog.text
