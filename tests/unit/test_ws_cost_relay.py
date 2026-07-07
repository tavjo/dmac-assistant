from __future__ import annotations

from dmac_assistant.streamjson import StreamEvent
from dmac_assistant.ws import stream_event_to_ws_frames


def _ended_frame(payload: dict) -> dict:
    frames = stream_event_to_ws_frames(
        StreamEvent(kind="event", payload={"type": "result", **payload}),
        current_session_id="sess-123",
    )
    assert len(frames) == 1
    assert frames[0]["type"] == "session_ended"
    return frames[0]


def test_cost_relay_exact_usage():
    usage = {
        "input_tokens": 12,
        "output_tokens": 34,
        "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 6,
    }

    frame = _ended_frame({"usage": usage, "total_cost_usd": 0.012345})

    assert frame == {
        "type": "session_ended",
        "session_id": "sess-123",
        "usage": usage,
        "total_cost_usd": 0.012345,
    }


def test_cost_relay_absent_total_cost_none():
    usage = {"input_tokens": 1, "output_tokens": 2}

    frame = _ended_frame({"usage": usage})

    assert frame["usage"] is usage
    assert frame["total_cost_usd"] is None


def test_cost_relay_extra_result_fields():
    usage = {"input_tokens": 3, "output_tokens": 4}

    frame = _ended_frame(
        {
            "usage": usage,
            "total_cost_usd": 0.5,
            "subtype": "success",
            "duration_ms": 42,
            "session_id": "claude-side-session",
        }
    )

    assert frame == {
        "type": "session_ended",
        "session_id": "sess-123",
        "usage": usage,
        "total_cost_usd": 0.5,
    }


def test_cost_relay_zero_total_cost():
    frame = _ended_frame({"usage": {"input_tokens": 0}, "total_cost_usd": 0})

    assert frame["usage"] == {"input_tokens": 0}
    assert frame["total_cost_usd"] == 0


def test_cost_relay_usage_absent_total_present():
    frame = _ended_frame({"total_cost_usd": 0.01})

    assert frame == {
        "type": "session_ended",
        "session_id": "sess-123",
        "total_cost_usd": 0.01,
    }
