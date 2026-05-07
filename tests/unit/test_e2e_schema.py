"""
T2 — QueryRecord schema tests.

Plan: dmac-assistant-e2e-ui-test-2026-05-06 (DD-04, DD-07, DD-08, R1/N3).
Schema is the contract every downstream task in the e2e plan consumes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools.e2e.schema import QueryRecord, JUDGE_VERDICT_LITERALS


# ---------------------------------------------------------------------------
# Constants — assertions against authoritative spellings (R1 / N3 sync gate)
# ---------------------------------------------------------------------------

EXPECTED_VERDICT_SET = {
    "passed",
    "failed",
    "refused",
    "unsupported",
    "fabricated",
    "error",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_walkthrough_payload() -> dict:
    """A complete 12-field walkthrough payload — judge fields stay default None."""
    return {
        "query_id": "Search-Basic-1",
        "query_text": "Find all human samples in study X.",
        "started_at": "2026-05-06T15:00:00Z",
        "completed_at": "2026-05-06T15:00:12Z",
        "latency_seconds": 12.0,
        "cost_usd": 0.045,
        "answer_provided": True,
        "plugin_fidelity": True,
        "transcript_path": "evidence/run-2026-05-06/transcripts/query-01.jsonl",
        "screenshot_path": "evidence/run-2026-05-06/screenshots/query-01.png",
        "tool_use_summary": [{"tool": "nextseek-api-read", "count": 1}],
        "error": None,
        "ui_answer": "Found 12 human samples in study X.",
    }


@pytest.fixture
def fully_judged_payload(minimal_walkthrough_payload: dict) -> dict:
    """Payload with all 15 fields populated (post-T7 state)."""
    payload = dict(minimal_walkthrough_payload)
    payload.update(
        {
            "judge_verdict": "passed",
            "judge_reasoning": "Reply identifies the correct samples.",
            "judge_model": "gemini-2.0-pro",
        }
    )
    return payload


# ---------------------------------------------------------------------------
# Happy-path round-trip
# ---------------------------------------------------------------------------


def test_minimal_walkthrough_record_round_trips(minimal_walkthrough_payload: dict) -> None:
    record = QueryRecord(**minimal_walkthrough_payload)
    dumped = record.model_dump(mode="json")
    rehydrated = QueryRecord(**dumped)
    assert rehydrated == record


def test_fully_judged_record_round_trips(fully_judged_payload: dict) -> None:
    record = QueryRecord(**fully_judged_payload)
    dumped = record.model_dump(mode="json")
    rehydrated = QueryRecord(**dumped)
    assert rehydrated == record


# ---------------------------------------------------------------------------
# Judge field defaults (DD-04 — judge fields default to None until T7)
# ---------------------------------------------------------------------------


def test_judge_fields_default_to_none(minimal_walkthrough_payload: dict) -> None:
    record = QueryRecord(**minimal_walkthrough_payload)
    assert record.judge_verdict is None
    assert record.judge_reasoning is None
    assert record.judge_model is None


def test_judge_fields_can_be_set_independently(minimal_walkthrough_payload: dict) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["judge_verdict"] = "passed"
    payload["judge_reasoning"] = "Looks correct."
    payload["judge_model"] = "gemini-2.0-pro"
    record = QueryRecord(**payload)
    assert record.judge_verdict == "passed"
    assert record.judge_reasoning == "Looks correct."
    assert record.judge_model == "gemini-2.0-pro"


# ---------------------------------------------------------------------------
# Frozen model — immutability
# ---------------------------------------------------------------------------


def test_record_is_frozen(minimal_walkthrough_payload: dict) -> None:
    record = QueryRecord(**minimal_walkthrough_payload)
    with pytest.raises(ValidationError):
        record.query_id = "Different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Enum membership — authoritative spellings (R1 / N3 sync gate)
# ---------------------------------------------------------------------------


def test_judge_verdict_literal_set_matches_authoritative_spellings() -> None:
    assert set(JUDGE_VERDICT_LITERALS) == EXPECTED_VERDICT_SET


@pytest.mark.parametrize("verdict", sorted(EXPECTED_VERDICT_SET))
def test_each_valid_verdict_accepted(
    verdict: str, minimal_walkthrough_payload: dict
) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["judge_verdict"] = verdict
    record = QueryRecord(**payload)
    assert record.judge_verdict == verdict


@pytest.mark.parametrize(
    "bad_verdict",
    [
        "PASSED",  # case mismatch
        "pass",  # truncation
        "FAIL",  # chat_nextseek's Score enum spelling — must NOT collide
        "PARTIAL",  # chat_nextseek's Score enum spelling — must NOT collide
        "ok",
        "true",
        "",
    ],
)
def test_invalid_verdict_rejected(
    bad_verdict: str, minimal_walkthrough_payload: dict
) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["judge_verdict"] = bad_verdict
    with pytest.raises(ValidationError):
        QueryRecord(**payload)


# ---------------------------------------------------------------------------
# 12 walkthrough field types — Pydantic constraint coverage
# ---------------------------------------------------------------------------


def test_latency_seconds_must_be_non_negative(minimal_walkthrough_payload: dict) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["latency_seconds"] = -0.1
    with pytest.raises(ValidationError):
        QueryRecord(**payload)


def test_cost_usd_must_be_non_negative(minimal_walkthrough_payload: dict) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["cost_usd"] = -1.0
    with pytest.raises(ValidationError):
        QueryRecord(**payload)


def test_query_id_required(minimal_walkthrough_payload: dict) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload.pop("query_id")
    with pytest.raises(ValidationError):
        QueryRecord(**payload)


def test_error_field_accepts_string_or_none(minimal_walkthrough_payload: dict) -> None:
    payload_with_err = dict(minimal_walkthrough_payload)
    payload_with_err["error"] = "Bridge timeout after 30s"
    record = QueryRecord(**payload_with_err)
    assert record.error == "Bridge timeout after 30s"
    payload_no_err = dict(minimal_walkthrough_payload)
    payload_no_err["error"] = None
    record = QueryRecord(**payload_no_err)
    assert record.error is None


def test_tool_use_summary_accepts_list_of_dicts(minimal_walkthrough_payload: dict) -> None:
    payload = dict(minimal_walkthrough_payload)
    payload["tool_use_summary"] = [
        {"tool": "nextseek-api-read", "count": 2},
        {"tool": "Read", "count": 5},
    ]
    record = QueryRecord(**payload)
    assert len(record.tool_use_summary) == 2
    assert record.tool_use_summary[0]["tool"] == "nextseek-api-read"


# ---------------------------------------------------------------------------
# Construction-time None defaults for judge fields (DD-04)
# ---------------------------------------------------------------------------


def test_record_constructible_without_judge_fields(minimal_walkthrough_payload: dict) -> None:
    """Walkthrough phase (T6) writes records before judging — judge fields are None."""
    record = QueryRecord(**minimal_walkthrough_payload)
    serialized = record.model_dump(mode="json")
    assert serialized["judge_verdict"] is None
    assert serialized["judge_reasoning"] is None
    assert serialized["judge_model"] is None


# ---------------------------------------------------------------------------
# ui_answer field (Amendment 4 / F-05-03 fix — replaces `_ui_answer` private key)
# ---------------------------------------------------------------------------


def test_ui_answer_field_round_trips(minimal_walkthrough_payload: dict) -> None:
    """T6 captures the UI's user-visible reply text into ui_answer; T7 judge reads it."""
    record = QueryRecord(**minimal_walkthrough_payload)
    assert record.ui_answer == "Found 12 human samples in study X."
    dumped = record.model_dump(mode="json")
    assert dumped["ui_answer"] == "Found 12 human samples in study X."
    rehydrated = QueryRecord(**dumped)
    assert rehydrated.ui_answer == record.ui_answer


def test_ui_answer_defaults_to_none_for_crashed_query(minimal_walkthrough_payload: dict) -> None:
    """A crashed query has no UI answer; ui_answer must accept None."""
    payload = dict(minimal_walkthrough_payload)
    payload["ui_answer"] = None
    payload["error"] = "Bridge timeout after 30s"
    record = QueryRecord(**payload)
    assert record.ui_answer is None
    assert record.error == "Bridge timeout after 30s"
