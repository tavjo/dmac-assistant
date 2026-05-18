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


@pytest.mark.asyncio
async def test_success_path_emits_router_decision_telemetry(monkeypatch, caplog):
    """Phase 7 residual debt #4: locked design called for per-turn structured
    telemetry (route, model_class, decision_latency_ms, reasoning_len) on the
    success path. Currently only the fallback path logs structured fields.

    Pins:
    - INFO-level log record with `router_decision` keyword in message or extra
    - `route` field carries the lowercase alias (`"nextseek_query"` /
      `"container_cc"`), NOT the BAML enum member name
    - `model_class` field carries the lowercase alias or None
    - `decision_latency_ms` is a non-negative number
    - `reasoning_len` is a non-negative int matching `len(decision.reasoning)`
    - R-03: `caplog.text` MUST NOT contain the reasoning text itself or the
      user query text
    """
    secret_reasoning = "user said NEXTSEEK_PASSWORD which should never log"
    expected = RouterDecision(
        route=Route.NextseekQuery,
        model_class=None,
        reasoning=secret_reasoning,
    )

    async def fake_route_query(input):  # noqa: A002
        return expected

    monkeypatch.setattr("dmac_assistant.router.agent.b.RouteQuery", fake_route_query)
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.INFO, logger="dmac_assistant.router.agent"):
        await agent.route("user_query_with_NEXTSEEK_PASSWORD_in_text")

    telemetry_records = [
        r for r in caplog.records
        if getattr(r, "route", None) is not None
        and getattr(r, "reasoning_len", None) is not None
    ]
    assert len(telemetry_records) == 1, (
        f"expected exactly one router-decision telemetry record; "
        f"got {len(telemetry_records)} (all records: {caplog.records})"
    )
    rec = telemetry_records[0]

    assert rec.route == "nextseek_query", (
        f"telemetry `route` field must use the lowercase alias "
        f"(`nextseek_query`/`container_cc`), not the BAML enum name. "
        f"Got: {rec.route!r}"
    )
    assert getattr(rec, "model_class", "MISSING") is None, (
        f"telemetry `model_class` must be None when the router returns "
        f"model_class=None (NS-route case). Got: {getattr(rec, 'model_class', 'MISSING')!r}"
    )
    latency = getattr(rec, "decision_latency_ms", None)
    assert isinstance(latency, (int, float)) and latency >= 0, (
        f"telemetry `decision_latency_ms` must be non-negative numeric; "
        f"got {latency!r}"
    )
    assert rec.reasoning_len == len(secret_reasoning), (
        f"telemetry `reasoning_len` must equal len(decision.reasoning); "
        f"got {rec.reasoning_len}, expected {len(secret_reasoning)}"
    )

    assert "NEXTSEEK_PASSWORD" not in caplog.text, (
        "R-03: reasoning text contains 'NEXTSEEK_PASSWORD' (a credential "
        "env-key) and must NEVER appear in caplog. Telemetry must log only "
        "reasoning_len, not the reasoning string itself."
    )
    assert secret_reasoning not in caplog.text, (
        "reasoning text must NEVER appear in caplog (R-03). "
        "Only reasoning_len is loggable."
    )
    assert "user_query_with" not in caplog.text, (
        "user query text must NEVER appear in caplog — it can include "
        "credentials or PII."
    )


@pytest.mark.asyncio
async def test_success_path_telemetry_includes_model_class_alias_for_cc(
    monkeypatch, caplog
):
    """When the router returns container_cc with a ModelClass, the
    `model_class` telemetry field carries the lowercase alias.
    """
    expected = RouterDecision(
        route=Route.ContainerCC,
        model_class=ModelClass.Opus,
        reasoning="hard reasoning needed",
    )

    async def fake_route_query(input):  # noqa: A002
        return expected

    monkeypatch.setattr("dmac_assistant.router.agent.b.RouteQuery", fake_route_query)
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.INFO, logger="dmac_assistant.router.agent"):
        await agent.route("complex refactoring task")

    telemetry_records = [
        r for r in caplog.records if getattr(r, "route", None) is not None
    ]
    assert len(telemetry_records) == 1
    rec = telemetry_records[0]
    assert rec.route == "container_cc"
    assert rec.model_class == "opus", (
        f"telemetry `model_class` must use the lowercase alias `opus` "
        f"(NOT the BAML enum name `Opus`). Got: {rec.model_class!r}"
    )


@pytest.mark.asyncio
async def test_fallback_path_does_not_emit_success_telemetry(monkeypatch, caplog):
    """Negative guard: when BAML raises, only the fallback log fires —
    not the success-path router_decision telemetry. Both records share the
    `router_fallback` distinguishing field; this test pins that distinction.
    """
    async def raising_route_query(input):  # noqa: A002
        raise RuntimeError("simulated GCP transport failure")

    monkeypatch.setattr(
        "dmac_assistant.router.agent.b.RouteQuery", raising_route_query
    )
    agent = RouterAgent(capabilities=_minimal_caps())

    with caplog.at_level(logging.DEBUG, logger="dmac_assistant.router.agent"):
        await agent.route("anything")

    success_records = [
        r for r in caplog.records
        if getattr(r, "route", None) is not None
        and not getattr(r, "router_fallback", False)
    ]
    assert success_records == [], (
        f"fallback path must NOT emit the success-path router_decision "
        f"telemetry record; got {len(success_records)}: {success_records}"
    )


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
