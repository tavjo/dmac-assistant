"""T04 stream-json parser tests: framing, init extraction, passthrough, errors."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _event(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


INIT_EVENT = {
    "type": "system",
    "subtype": "init",
    "session_id": "11111111-2222-3333-4444-555555555555",
    "model": "claude-sonnet-4-6",
    "cwd": "/home/user",
    "tools": ["Bash", "Edit"],
}
SECOND_INIT_EVENT = {
    "type": "system",
    "subtype": "init",
    "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "cwd": "/home/user",
}
ASSISTANT_EVENT = {
    "type": "assistant",
    "message": {"content": [{"type": "text", "text": "Hello"}]},
}
RESULT_EVENT = {"type": "result", "subtype": "success", "duration_ms": 42}


def _payloads(events: list) -> list[dict]:
    return [event.payload for event in events if event.kind == "event"]


def test_feed_single_complete_event_returns_list() -> None:
    from dmac_assistant.streamjson import StreamEvent, StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(_event(INIT_EVENT))

    assert isinstance(events, list)
    assert len(events) == 1
    assert isinstance(events[0], StreamEvent)
    assert events[0].kind == "event"
    assert events[0].payload == INIT_EVENT
    assert parser.session_id == INIT_EVENT["session_id"]


def test_feed_two_events_in_one_chunk_returns_two_entries_in_order() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(_event(INIT_EVENT) + _event(ASSISTANT_EVENT))

    assert _payloads(events) == [INIT_EVENT, ASSISTANT_EVENT]
    assert parser.session_id == INIT_EVENT["session_id"]


def test_feed_event_split_across_two_chunks_buffers_until_newline() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    full = _event(INIT_EVENT)
    midpoint = len(full) // 2

    assert parser.feed(full[:midpoint]) == []
    assert parser.session_id is None

    events = parser.feed(full[midpoint:])
    assert _payloads(events) == [INIT_EVENT]
    assert parser.session_id == INIT_EVENT["session_id"]


def test_feed_event_split_across_three_chunks_with_empty_middle() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    full = _event(ASSISTANT_EVENT)

    assert parser.feed(full[:10]) == []
    assert parser.feed(b"") == []
    events = parser.feed(full[10:])
    assert _payloads(events) == [ASSISTANT_EVENT]


def test_feed_empty_chunk_is_noop() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    assert parser.feed(b"") == []
    assert parser.session_id is None


def test_feed_invalid_json_returns_error_event() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(b"not-json-at-all\n")

    assert len(events) == 1
    event = events[0]
    assert event.kind == "error"
    assert event.payload is None
    assert event.error is not None
    assert event.error.line == b"not-json-at-all"
    assert event.error.reason


def test_feed_good_event_followed_by_bad_line_returns_both_in_order() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(_event(INIT_EVENT) + b"not-json\n" + _event(ASSISTANT_EVENT))

    assert [event.kind for event in events] == ["event", "error", "event"]
    assert events[0].payload == INIT_EVENT
    assert events[1].error is not None
    assert events[2].payload == ASSISTANT_EVENT


def test_feed_non_init_event_leaves_session_id_none() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(_event(ASSISTANT_EVENT))
    assert parser.session_id is None


def test_feed_init_then_assistant_keeps_session_id() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(_event(INIT_EVENT))
    parser.feed(_event(ASSISTANT_EVENT))
    assert parser.session_id == INIT_EVENT["session_id"]


def test_feed_second_init_event_updates_session_id() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(_event(INIT_EVENT))
    parser.feed(_event(SECOND_INIT_EVENT))
    assert parser.session_id == SECOND_INIT_EVENT["session_id"]


def test_feed_non_object_top_level_json_is_error_event() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(b"42\n")

    assert len(events) == 1
    assert events[0].kind == "error"
    assert events[0].error is not None
    assert "object" in events[0].error.reason


def test_feed_blank_lines_are_ignored() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(b"\n\n" + _event(RESULT_EVENT) + b"\n")

    assert _payloads(events) == [RESULT_EVENT]


def test_feed_rejects_non_bytes_argument() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    with pytest.raises(TypeError, match="bytes"):
        parser.feed("not-bytes")  # type: ignore[arg-type]


def test_flush_returns_error_for_trailing_partial_line() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(b'{"type":"assistant"')

    events = parser.flush()

    assert len(events) == 1
    assert events[0].kind == "error"
    assert events[0].error is not None
    assert events[0].error.line == b'{"type":"assistant"'


def test_flush_after_complete_lines_returns_no_extra_events() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(_event(ASSISTANT_EVENT))

    assert parser.flush() == []


def test_flush_after_blank_trailing_buffer_is_empty() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(b"\n")
    assert parser.flush() == []


def test_repr_hides_internal_buffer_contents() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    parser.feed(b'{"secret":"value"')

    assert "value" not in repr(parser)
    assert "<hidden>" in repr(parser)


def test_fixture_version_matches_pinned_image() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"claude-code@([0-9.]+)", dockerfile)
    assert match is not None
    version = match.group(1)

    fixture_path = FIXTURE_DIR / f"streamjson_init_{version}.jsonl"
    assert fixture_path.exists(), f"missing fixture for pinned Claude Code {version}"


def test_fixture_file_parses_and_sets_session_id() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    fixture_path = FIXTURE_DIR / "streamjson_init_2.1.92.jsonl"
    parser = StreamJsonParser()
    events = parser.feed(fixture_path.read_bytes())

    assert len(events) == 3
    assert events[0].kind == "event"
    assert parser.session_id == INIT_EVENT["session_id"]


def test_feed_invalid_utf8_surfaces_error_event() -> None:
    from dmac_assistant.streamjson import StreamJsonParser

    parser = StreamJsonParser()
    events = parser.feed(b"\xff\xfe\n")

    assert len(events) == 1
    assert events[0].kind == "error"
    assert events[0].error is not None
