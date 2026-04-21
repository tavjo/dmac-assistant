"""Unit tests for the stream-json parser harness."""
from __future__ import annotations

import json

import pytest

from tests.harness.stream_json import (
    StreamJSONParseError,
    StreamJSONParser,
    ToolUseEvent,
    parse_stream,
)


@pytest.fixture
def two_turn_stream() -> bytes:
    events = [
        {"type": "system", "subtype": "init", "session_id": "s-1"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "second"}]}},
        {
            "type": "result",
            "subtype": "success",
            "usage": {"input_tokens": 42, "output_tokens": 7},
            "session_id": "s-1",
        },
    ]
    return b"\n".join(json.dumps(event).encode("utf-8") for event in events) + b"\n"


@pytest.fixture
def utf8_stream() -> bytes:
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "cafe \u2615"}]}},
        {"type": "result", "subtype": "success", "usage": {"input_tokens": 1}},
    ]
    return (
        b"\n".join(
            json.dumps(event, ensure_ascii=False).encode("utf-8") for event in events
        )
        + b"\n"
    )


def test_parse_stream_yields_all_events(two_turn_stream: bytes) -> None:
    events = list(parse_stream(two_turn_stream))
    assert len(events) == 4
    assert events[0]["type"] == "system"
    assert events[-1]["type"] == "result"


def test_parse_stream_handles_utf8(utf8_stream: bytes) -> None:
    events = list(parse_stream(utf8_stream))
    assert events[0]["message"]["content"][0]["text"] == "cafe \u2615"


def test_parse_stream_skips_blank_lines() -> None:
    raw = b'\n\n{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}\n\n'
    events = list(parse_stream(raw))
    assert len(events) == 1
    assert events[0]["message"]["content"][0]["text"] == "x"


def test_parse_stream_raises_on_malformed_line() -> None:
    raw = b'{"type":"assistant"}\nthis-is-not-json\n'
    with pytest.raises(StreamJSONParseError) as excinfo:
        list(parse_stream(raw))
    assert "line 2" in str(excinfo.value)


def test_parse_stream_tolerates_malformed_when_strict_false() -> None:
    raw = (
        b'{"type":"assistant"}\nthis-is-not-json\n'
        b'{"type":"result","usage":{"input_tokens":1}}\n'
    )
    events = list(parse_stream(raw, strict=False))
    assert len(events) == 2
    assert events[-1]["type"] == "result"


def test_parse_stream_accepts_str_input() -> None:
    events = list(parse_stream('{"type":"assistant"}\n'))
    assert events == [{"type": "assistant"}]


def test_parse_stream_handles_trailing_partial_line_strict_false() -> None:
    raw = b'{"type":"assistant"}\n{"type":"resu'
    events = list(parse_stream(raw, strict=False))
    assert len(events) == 1


def test_parser_collects_assistant_text(two_turn_stream: bytes) -> None:
    parser = StreamJSONParser()
    for event in parse_stream(two_turn_stream):
        parser.feed(event)
    assert parser.assistant_texts == ["first", "second"]
    assert parser.final_usage == {"input_tokens": 42, "output_tokens": 7}


def test_parser_no_usage_when_no_result_event() -> None:
    parser = StreamJSONParser()
    for event in parse_stream(
        b'{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}\n'
    ):
        parser.feed(event)
    assert parser.final_usage is None
    assert parser.assistant_texts == ["x"]


def test_parser_handles_assistant_without_content_gracefully() -> None:
    parser = StreamJSONParser()
    parser.feed({"type": "assistant"})
    parser.feed({"type": "assistant", "message": {}})
    parser.feed({"type": "assistant", "message": {"content": []}})
    parser.feed(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1"}]}}
    )
    assert parser.assistant_texts == []


def test_parser_contains_nonce_helper() -> None:
    parser = StreamJSONParser()
    parser.feed(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "hello BEDROCK_PING_abc123 world",
                    }
                ]
            },
        }
    )
    assert parser.contains_text("BEDROCK_PING_abc123") is True
    assert parser.contains_text("NOT_THERE") is False


def test_parser_ignores_unknown_event_types() -> None:
    parser = StreamJSONParser()
    parser.feed({"type": "mystery", "payload": 1})
    parser.feed({"type": "result", "usage": {"input_tokens": 3}})
    assert parser.final_usage == {"input_tokens": 3}


def test_parse_stream_empty_input() -> None:
    assert list(parse_stream(b"")) == []
    assert list(parse_stream("")) == []


def test_parser_captures_tool_use_events() -> None:
    parser = StreamJSONParser()
    parser.feed(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "calling plugin"},
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "nextseek-call",
                        "input": {"op": "ListAssays"},
                    },
                ]
            },
        }
    )
    events = parser.tool_use_events()
    assert len(events) == 1
    assert events[0] == ToolUseEvent(
        id="tool_1", name="nextseek-call", input={"op": "ListAssays"}
    )
    assert parser.assistant_texts == ["calling plugin"]


def test_parser_tool_use_without_input_dict() -> None:
    parser = StreamJSONParser()
    parser.feed(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "whatever",
                        "input": "not-a-dict",
                    }
                ]
            },
        }
    )
    events = parser.tool_use_events()
    assert len(events) == 1
    assert events[0].input is None
    assert events[0].name == "whatever"


def test_parser_skips_non_dict_content_blocks() -> None:
    """Defensive: malformed event with a non-dict content block must not crash."""
    parser = StreamJSONParser()
    parser.feed(
        {
            "type": "assistant",
            "message": {"content": ["string-not-a-dict", {"type": "text", "text": "ok"}]},
        }
    )
    assert parser.assistant_texts == ["ok"]
    assert parser.tool_use_events() == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_parse_stream_decodes_encodings(encoding: str) -> None:
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "x"}]},
    }
    raw = json.dumps(event).encode(encoding) + b"\n"
    events = list(parse_stream(raw))
    assert events[0]["message"]["content"][0]["text"] == "x"
