"""Tests for dmac_assistant.router.agent."""
from __future__ import annotations

import asyncio
import logging

import pytest

from dmac_assistant.router.agent import RouterAgent
from dmac_assistant.router.baml_client.types import (
    ModelClass,
    Route,
    RouteCapability,
    RouterDecision,
    TaskFamily,
)


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
            description="NS route.",
            tools=["entity_agent"],
            best_for=None,
            not_for=None,
            task_families=[
                TaskFamily(name="x", description="x", example_queries=["q"])
            ],
        ),
        RouteCapability(
            route_name="container_cc",
            description="CC route.",
            tools=["bash"],
            best_for=None,
            not_for=None,
            task_families=[
                TaskFamily(name="y", description="y", example_queries=["q"])
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_happy_path_returns_baml_decision(monkeypatch):
    expected = RouterDecision(
        route=Route.NextseekQuery,
        model_class=None,
        reasoning="picked NS for sample search",
    )

    async def fake_route_query(input):  # noqa: A002
        return expected

    monkeypatch.setattr("dmac_assistant.router.agent.b.RouteQuery", fake_route_query)
    agent = RouterAgent(capabilities=_minimal_caps())

    got = await agent.route("Find me mice treated with NDMA.")

    assert got.route == Route.NextseekQuery
    assert got.model_class is None
    assert got.reasoning == "picked NS for sample search"


@pytest.mark.asyncio
async def test_happy_path_passes_capabilities_to_baml(monkeypatch):
    captured = {}

    async def capturing_route_query(input):  # noqa: A002
        captured["routes"] = list(input.routes)
        captured["user_query"] = input.user_query
        return RouterDecision(
            route=Route.ContainerCC,
            model_class=ModelClass.Sonnet,
            reasoning="default",
        )

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", capturing_route_query
    )
    caps = _minimal_caps()
    agent = RouterAgent(capabilities=caps)

    await agent.route("test query")

    assert captured["user_query"] == "test query"
    assert len(captured["routes"]) == 2
    assert captured["routes"][0].route_name == "nextseek_query"


@pytest.mark.asyncio
async def test_happy_path_cc_with_null_model_class_passes_through(monkeypatch):
    expected = RouterDecision(
        route=Route.ContainerCC,
        model_class=None,
        reasoning="router said cc but skipped class",
    )

    async def fake_route_query(input):  # noqa: A002
        return expected

    monkeypatch.setattr("dmac_assistant.router.agent.b.RouteQuery", fake_route_query)
    agent = RouterAgent(capabilities=_minimal_caps())

    got = await agent.route("ambiguous query")

    assert got.route == Route.ContainerCC
    assert got.model_class is None
    assert got.reasoning == "router said cc but skipped class"


@pytest.mark.asyncio
async def test_baml_raises_exception_returns_fallback(monkeypatch, caplog):
    async def raising_route_query(input):  # noqa: A002
        raise RuntimeError("simulated GCP transport failure")

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", raising_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.WARNING, logger="dmac_assistant.router.agent"):
        decision = await agent.route("anything")

    assert decision.route == Route.ContainerCC
    assert decision.model_class == ModelClass.Sonnet
    assert decision.reasoning == "<router_unavailable>"


@pytest.mark.asyncio
async def test_baml_raises_baseexception_subclass_returns_fallback(monkeypatch):
    class CustomBase(BaseException):
        pass

    async def raising_route_query(input):  # noqa: A002
        raise CustomBase("simulated low-level error")

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", raising_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    decision = await agent.route("anything")

    assert decision.route == Route.ContainerCC
    assert decision.model_class == ModelClass.Sonnet
    assert decision.reasoning == "<router_unavailable>"


@pytest.mark.asyncio
async def test_cancelled_error_is_propagated(monkeypatch):
    async def cancelling_route_query(input):  # noqa: A002
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", cancelling_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with pytest.raises(asyncio.CancelledError):
        await agent.route("anything")


@pytest.mark.asyncio
async def test_fallback_log_carries_structured_fields(monkeypatch, caplog):
    async def raising_route_query(input):  # noqa: A002
        raise ValueError("schema mismatch")

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", raising_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.WARNING, logger="dmac_assistant.router.agent"):
        await agent.route("anything")

    matches = [
        record
        for record in caplog.records
        if getattr(record, "router_fallback", False)
        and getattr(record, "exc_type", None) == "ValueError"
    ]
    assert len(matches) == 1


def test_default_constructor_loads_capabilities(monkeypatch):
    call_count = {"n": 0}

    def fake_load():
        call_count["n"] += 1
        return _minimal_caps()

    monkeypatch.setattr("dmac_assistant.router.agent.load_capabilities", fake_load)

    RouterAgent()

    assert call_count["n"] == 1


def test_explicit_capabilities_bypasses_load(monkeypatch):
    raised_if_called = []

    def boom():
        raised_if_called.append(True)
        raise AssertionError("load_capabilities() should not be called")

    monkeypatch.setattr("dmac_assistant.router.agent.load_capabilities", boom)

    RouterAgent(capabilities=_minimal_caps())

    assert not raised_if_called
