"""Tests for NS event to WebSocket frame adaptation."""
from __future__ import annotations

import logging

import pytest

from dmac_assistant.ns_adapter import (
    KNOWN_QUERY_ERROR_AGENTS,
    ns_event_to_frames,
)

SESSION_ID = "ns-abcdef0123456789"


@pytest.mark.parametrize(
    "event_name",
    ["agent_started", "agent_complete", "search_started", "search_complete"],
)
def test_tool_use_event_emits_single_tool_use_frame(event_name: str) -> None:
    payload = {"agent": "parser", "extra": "anything"}
    frames, is_terminal = ns_event_to_frames(
        {"event": event_name, "payload": payload},
        session_id=SESSION_ID,
        event_index=7,
    )
    assert is_terminal is False
    assert frames == [
        {
            "type": "tool_use",
            "tool": f"ns:{event_name}",
            "input": payload,
            "id": "ns-evt-7",
        }
    ]


def test_tool_use_id_uses_event_index_passed_in() -> None:
    frames, _ = ns_event_to_frames(
        {"event": "agent_started", "payload": {"agent": "graph"}},
        session_id=SESSION_ID,
        event_index=42,
    )
    assert frames[0]["id"] == "ns-evt-42"


def test_accepts_positional_session_id_and_event_index() -> None:
    frames, is_terminal = ns_event_to_frames(
        {"event": "agent_started", "payload": {"agent": "graph"}},
        SESSION_ID,
        13,
    )
    assert is_terminal is False
    assert frames[0]["id"] == "ns-evt-13"


def test_query_complete_success_emits_assistant_message_and_session_ended() -> None:
    frames, is_terminal = ns_event_to_frames(
        {
            "event": "query_complete",
            "payload": {"reply": "Hello, world.", "bundle_id": "internal-bundle"},
        },
        session_id=SESSION_ID,
        event_index=99,
    )
    assert is_terminal is True
    assert frames == [
        {"type": "assistant_message", "content": "Hello, world."},
        {"type": "session_ended", "session_id": SESSION_ID},
    ]


@pytest.mark.parametrize(
    ("status_value", "expected_detail"),
    [("error", "error"), ("partial", "partial"), ("failure", "failure")],
)
def test_query_complete_check_1_status_signals_failure(
    status_value: str,
    expected_detail: str,
) -> None:
    payload = {
        "status": status_value,
        "reply": "secretpw=hunter2 should NOT leak",
        "bundle_id": None,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=1,
    )
    assert is_terminal is True
    assert frames == [
        {
            "type": "error",
            "reason": "ns_query_complete_with_error",
            "detail": expected_detail,
        },
        {"type": "session_ended", "session_id": SESSION_ID},
    ]
    for frame in frames:
        assert "hunter2" not in str(frame)


def test_query_complete_check_2_error_type_signals_failure() -> None:
    payload = {
        "error_type": "GCPRateLimit",
        "reply": "ignored should not leak",
        "bundle_id": None,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=2,
    )
    assert is_terminal is True
    assert frames == [
        {"type": "error", "reason": "ns_query_complete_with_error", "detail": "unknown"},
        {"type": "session_ended", "session_id": SESSION_ID},
    ]


def test_query_complete_check_3_top_level_error_signals_failure() -> None:
    payload = {
        "error": "credential=blah must not leak",
        "reply": "ignored",
        "bundle_id": None,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=3,
    )
    assert is_terminal is True
    assert frames[0]["detail"] == "unknown"
    for frame in frames:
        assert "credential=blah" not in str(frame)


def test_query_complete_check_4_debug_error_signals_failure() -> None:
    payload = {
        "reply": "must not leak credential=hunter2",
        "debug": {"error": "AWS_BEARER_TOKEN_BEDROCK=secret-xyz"},
        "bundle_id": None,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=4,
    )
    assert is_terminal is True
    assert frames == [
        {
            "type": "error",
            "reason": "ns_query_complete_with_error",
            "detail": "debug_error",
        },
        {"type": "session_ended", "session_id": SESSION_ID},
    ]
    for frame in frames:
        assert "hunter2" not in str(frame)
        assert "AWS_BEARER_TOKEN_BEDROCK" not in str(frame)


def test_query_complete_check_5_debug_fatal_error_signals_failure() -> None:
    payload = {
        "reply": "AWS_BEARER_TOKEN_BEDROCK=top-secret",
        "debug": {
            "fatal_error": "AWS_BEARER_TOKEN_BEDROCK=top-secret",
            "agent": "parser",
        },
        "bundle_id": None,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=5,
    )
    assert is_terminal is True
    assert frames == [
        {
            "type": "error",
            "reason": "ns_query_complete_with_error",
            "detail": "debug_fatal_error",
        },
        {"type": "session_ended", "session_id": SESSION_ID},
    ]
    for frame in frames:
        assert "AWS_BEARER_TOKEN_BEDROCK" not in str(frame)
        assert "top-secret" not in str(frame)


@pytest.mark.parametrize(
    ("payload_extra", "expected_detail"),
    [
        ({"error_type": {"kind": "GCPRateLimit"}}, "unknown"),
        ({"error": ["credential=blah"]}, "unknown"),
        ({"debug": {"error": {"message": "AWS_BEARER_TOKEN_BEDROCK=secret"}}}, "debug_error"),
        (
            {"debug": {"fatal_error": ["AWS_BEARER_TOKEN_BEDROCK=secret"]}},
            "debug_fatal_error",
        ),
    ],
)
def test_query_complete_non_string_failure_signals_drop_reply(
    payload_extra: dict[str, object],
    expected_detail: str,
) -> None:
    payload = {
        "reply": "AWS_BEARER_TOKEN_BEDROCK=top-secret should not leak",
        "bundle_id": None,
        **payload_extra,
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=6,
    )
    assert is_terminal is True
    assert frames == [
        {
            "type": "error",
            "reason": "ns_query_complete_with_error",
            "detail": expected_detail,
        },
        {"type": "session_ended", "session_id": SESSION_ID},
    ]
    for frame in frames:
        assert "AWS_BEARER_TOKEN_BEDROCK" not in str(frame)
        assert "top-secret" not in str(frame)


def test_query_complete_check_5_llm_fatal_error_caplog_clean(caplog) -> None:
    payload = {
        "reply": "AWS_BEARER_TOKEN_BEDROCK=secret",
        "debug": {"fatal_error": "AWS_BEARER_TOKEN_BEDROCK=secret", "agent": "parser"},
        "bundle_id": None,
    }
    with caplog.at_level(logging.DEBUG):
        ns_event_to_frames(
            {"event": "query_complete", "payload": payload},
            session_id=SESSION_ID,
            event_index=5,
        )
    assert "AWS_BEARER_TOKEN_BEDROCK" not in caplog.text
    assert "secret" not in caplog.text


def test_check_1_fires_before_check_4_when_both_signals_present() -> None:
    payload = {"status": "error", "debug": {"error": "also set"}, "reply": "redacted"}
    frames, _ = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=10,
    )
    assert frames[0]["detail"] == "error"


def test_check_1_unknown_status_value_maps_to_unknown_detail() -> None:
    payload = {"status": "ok", "reply": "all good"}
    frames, _ = ns_event_to_frames(
        {"event": "query_complete", "payload": payload},
        session_id=SESSION_ID,
        event_index=11,
    )
    assert frames == [
        {"type": "assistant_message", "content": "all good"},
        {"type": "session_ended", "session_id": SESSION_ID},
    ]


@pytest.mark.parametrize(
    "agent",
    [
        "catalog",
        "entity",
        "parser",
        "api",
        "search",
        "graph",
        "reporter",
        "report_writer",
        "chatter",
        "memory",
        "system",
        "planner",
        "context_engineer",
        "evaluator",
    ],
)
def test_query_error_known_agents_pass_through_to_detail(agent: str) -> None:
    payload = {
        "agent": agent,
        "error": "NEXTSEEK_PASSWORD=hunter2 must NEVER leak",
    }
    frames, is_terminal = ns_event_to_frames(
        {"event": "query_error", "payload": payload},
        session_id=SESSION_ID,
        event_index=20,
    )
    assert is_terminal is True
    assert frames == [
        {"type": "error", "reason": "ns_query_error", "detail": agent},
        {"type": "session_ended", "session_id": SESSION_ID},
    ]
    for frame in frames:
        assert "hunter2" not in str(frame)
        assert "NEXTSEEK_PASSWORD" not in str(frame)


def test_query_error_caplog_does_not_leak_payload_error(caplog) -> None:
    payload = {
        "agent": "parser",
        "error": "NEXTSEEK_PASSWORD=hunter2 AWS_BEARER_TOKEN_BEDROCK=secret-xyz",
    }
    with caplog.at_level(logging.DEBUG):
        ns_event_to_frames(
            {"event": "query_error", "payload": payload},
            session_id=SESSION_ID,
            event_index=20,
        )
    assert "NEXTSEEK_PASSWORD" not in caplog.text
    assert "AWS_BEARER_TOKEN_BEDROCK" not in caplog.text
    assert "hunter2" not in caplog.text
    assert "secret-xyz" not in caplog.text


@pytest.mark.parametrize(
    "agent_value",
    [None, "", "external-agent-not-in-union", 42, ["not", "string"], {"k": "v"}],
)
def test_query_error_missing_or_unknown_agent_maps_to_unknown(
    agent_value: object,
) -> None:
    payload: dict[str, object] = {"error": "ignored"}
    if agent_value is not None:
        payload["agent"] = agent_value
    frames, _ = ns_event_to_frames(
        {"event": "query_error", "payload": payload},
        session_id=SESSION_ID,
        event_index=21,
    )
    assert frames[0]["detail"] == "unknown"


def test_known_query_error_agents_constant_matches_spec_union() -> None:
    assert KNOWN_QUERY_ERROR_AGENTS == frozenset(
        {
            "catalog",
            "entity",
            "parser",
            "api",
            "search",
            "graph",
            "reporter",
            "report_writer",
            "chatter",
            "memory",
            "system",
            "planner",
            "context_engineer",
            "evaluator",
        }
    )


def test_unknown_event_returns_empty_frames_and_logs_debug(caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        frames, is_terminal = ns_event_to_frames(
            {"event": "some_future_event_name", "payload": {}},
            session_id=SESSION_ID,
            event_index=30,
        )
    assert frames == []
    assert is_terminal is False
    assert "some_future_event_name" in caplog.text


@pytest.mark.parametrize("internal_event", ["ns_runner_error", "ns_runner_error_type"])
def test_runner_internal_events_drop_to_debug_log(
    internal_event: str,
    caplog,
) -> None:
    with caplog.at_level(logging.DEBUG):
        frames, is_terminal = ns_event_to_frames(
            {"event": internal_event, "payload": {"error_type": "RedactedByRunner"}},
            session_id=SESSION_ID,
            event_index=31,
        )
    assert frames == []
    assert is_terminal is False


def test_double_terminal_event_idempotent() -> None:
    events = [
        {"event": "query_error", "payload": {"agent": "parser", "error": "ignored"}},
        {"event": "query_complete", "payload": {"reply": "should never reach the WS"}},
    ]
    terminal_emitted = False
    emitted: list[dict[str, object]] = []
    for idx, event in enumerate(events):
        if terminal_emitted:
            continue
        frames, is_terminal = ns_event_to_frames(
            event,
            session_id=SESSION_ID,
            event_index=idx,
        )
        emitted.extend(frames)
        if is_terminal:
            terminal_emitted = True
    session_ended_count = sum(1 for frame in emitted if frame["type"] == "session_ended")
    assert session_ended_count == 1
    assert "should never reach the WS" not in str(emitted)


@pytest.mark.parametrize("bad_event", [{"payload": {"x": "y"}}, {"event": 42}])
def test_event_without_string_event_field_treated_as_unknown(
    bad_event: dict[str, object],
    caplog,
) -> None:
    with caplog.at_level(logging.DEBUG):
        frames, is_terminal = ns_event_to_frames(
            bad_event,
            session_id=SESSION_ID,
            event_index=40,
        )
    assert frames == []
    assert is_terminal is False


@pytest.mark.parametrize("payload_value", [None, "bad", ["bad"]])
def test_event_without_payload_field_uses_empty_dict(payload_value: object) -> None:
    event = {"event": "agent_started"}
    if payload_value is not None:
        event["payload"] = payload_value
    frames, _ = ns_event_to_frames(
        event,
        session_id=SESSION_ID,
        event_index=41,
    )
    assert frames == [
        {
            "type": "tool_use",
            "tool": "ns:agent_started",
            "input": {},
            "id": "ns-evt-41",
        }
    ]
