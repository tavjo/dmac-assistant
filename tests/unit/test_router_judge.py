"""Phase 7 Residual #5 — offline unit tests for ``tools/e2e/router_judge.py``.

These tests pin three load-bearing behaviours:

  1. ``extract_reply_text`` returns the last ``assistant_message.content``
     before ``session_ended`` for both router paths.
  2. ``summarise_frames`` emits a stable one-line summary.
  3. ``judge_reply`` accepts an injected BAML client (mocked here — no live
     Gemini call), normalises the verdict, and surfaces any BAML failure as
     ``INCONCLUSIVE`` instead of raising.

Coverage of the live judge is provided by the gated integration test in
``tests/integration/test_run_router_e2e.py`` (requires ``GCP_API_KEY``).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.e2e.router_judge import (  # noqa: E402
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    extract_reply_text,
    judge_reply,
    summarise_frames,
)


@pytest.fixture
def allow_unix_socket_only():
    """pytest-asyncio's loop creation calls socketpair() on AF_UNIX; the
    repo-wide ``--disable-socket`` blocks it. Same workaround used by
    ``tests/unit/test_app_health.py`` and ``test_auth.py``.
    """
    import pytest_socket

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


# --- extract_reply_text --------------------------------------------------


def test_extract_returns_last_assistant_message_ns_route() -> None:
    """NS-route terminal text is the last assistant_message before session_ended."""
    frames = [
        {"type": "route_decided", "route": "nextseek_query"},
        {"type": "session_started", "session_id": "ns-abc"},
        {"type": "tool_use", "tool": "ns:agent_complete"},
        {
            "type": "assistant_message",
            "content": "Found 14 mice treated with NDMA across 3 studies.",
        },
        {"type": "session_ended", "session_id": "ns-abc"},
    ]
    assert (
        extract_reply_text(frames)
        == "Found 14 mice treated with NDMA across 3 studies."
    )


def test_extract_returns_last_assistant_message_cc_route_multiple() -> None:
    """For CC route, multiple assistant_message frames are common — take the last."""
    frames = [
        {"type": "route_decided", "route": "container_cc"},
        {"type": "session_started", "session_id": "cc-xyz"},
        {"type": "assistant_message", "content": "Let me investigate."},
        {"type": "tool_use", "tool": "Bash"},
        {"type": "assistant_message", "content": "First draft of the chart."},
        {"type": "tool_use", "tool": "Bash"},
        {"type": "assistant_message", "content": "The chart is saved at /scratch/x.svg."},
        {"type": "session_ended", "session_id": "cc-xyz"},
    ]
    assert extract_reply_text(frames) == "The chart is saved at /scratch/x.svg."


def test_extract_falls_back_to_error_reason_when_no_assistant_message() -> None:
    """NS-route truncation case: only an error frame, no assistant_message."""
    frames = [
        {"type": "route_decided", "route": "nextseek_query"},
        {"type": "session_started", "session_id": "ns-trunc"},
        {"type": "error", "reason": "ns_exec_truncated"},
        {"type": "session_ended", "session_id": "ns-trunc"},
    ]
    out = extract_reply_text(frames)
    assert "ns_exec_truncated" in out
    assert out.startswith("<error frame:")


def test_extract_returns_empty_when_no_terminal_text() -> None:
    frames = [
        {"type": "route_decided", "route": "container_cc"},
        {"type": "session_started", "session_id": "cc-empty"},
        {"type": "session_ended", "session_id": "cc-empty"},
    ]
    assert extract_reply_text(frames) == ""


def test_extract_skips_empty_or_non_string_assistant_messages() -> None:
    frames = [
        {"type": "assistant_message", "content": ""},
        {"type": "assistant_message", "content": None},
        {"type": "assistant_message", "content": "real reply"},
        {"type": "assistant_message"},  # missing content
    ]
    # "real reply" is the last non-empty string content seen.
    assert extract_reply_text(frames) == "real reply"


# --- summarise_frames ----------------------------------------------------


def test_summarise_frames_counts_and_preserves_first_seen_order() -> None:
    frames = [
        {"type": "route_decided"},
        {"type": "session_started"},
        {"type": "tool_use"},
        {"type": "tool_use"},
        {"type": "assistant_message"},
        {"type": "tool_use"},
        {"type": "session_ended"},
    ]
    summary = summarise_frames(frames)
    assert summary == (
        "route_decided x 1, session_started x 1, tool_use x 3, "
        "assistant_message x 1, session_ended x 1"
    )


def test_summarise_frames_ignores_non_string_types() -> None:
    frames = [{"type": "ok"}, {"type": 7}, {"type": None}, {}, {"type": "ok"}]
    assert summarise_frames(frames) == "ok x 2"


# --- judge_reply ---------------------------------------------------------


class _MockClient:
    """Async-shaped stand-in for ``baml_client.b`` with a JudgeRouterAnswer method."""

    def __init__(self, *, verdict: str = "PASS", reasoning: str = "ok") -> None:
        self._verdict = verdict
        self._reasoning = reasoning
        self.calls: list[dict] = []

    async def JudgeRouterAnswer(self, *, input):  # noqa: N802 — matches BAML name
        # Tolerate both RouterJudgeInput pydantic and bare-dict inputs so the
        # mock survives schema changes in the generated BAML client.
        def _pull(key: str) -> str:
            if hasattr(input, key):
                return getattr(input, key)
            if isinstance(input, dict):
                return input.get(key, "")
            return ""

        self.calls.append(
            {
                "query_id": _pull("query_id"),
                "reply_text": _pull("reply_text"),
                "actual_route": _pull("actual_route"),
            }
        )
        return SimpleNamespace(verdict=self._verdict, reasoning=self._reasoning)


@pytest.mark.asyncio
async def test_judge_reply_returns_pass_when_mock_says_pass(
    allow_unix_socket_only,
) -> None:
    client = _MockClient(verdict="PASS", reasoning="reply is on-topic")
    result = await judge_reply(
        query_id="Search-Basic-1",
        query_text="Find me mice treated with NDMA.",
        expected_route="nextseek_query",
        actual_route="nextseek_query",
        reply_text="Found 14 mice across 3 studies.",
        frames_summary="route_decided x 1, assistant_message x 1",
        baml_client=client,
    )
    assert result.verdict == VERDICT_PASS
    assert result.reasoning == "reply is on-topic"
    assert result.latency_seconds >= 0.0
    assert len(client.calls) == 1
    assert client.calls[0]["reply_text"] == "Found 14 mice across 3 studies."


@pytest.mark.asyncio
async def test_judge_reply_normalises_enum_dotted_form(
    allow_unix_socket_only,
) -> None:
    """BAML may render the verdict as 'RouterJudgeVerdict.Pass' — must normalise."""
    client = _MockClient(verdict="RouterJudgeVerdict.Pass", reasoning="x")
    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="container_cc",
        actual_route="container_cc",
        reply_text="ok",
        frames_summary="",
        baml_client=client,
    )
    assert result.verdict == VERDICT_PASS


@pytest.mark.asyncio
async def test_judge_reply_normalises_enum_member_name(
    allow_unix_socket_only,
) -> None:
    client = _MockClient(verdict="Inconclusive", reasoning="")
    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="container_cc",
        actual_route="container_cc",
        reply_text="ok",
        frames_summary="",
        baml_client=client,
    )
    assert result.verdict == VERDICT_INCONCLUSIVE


@pytest.mark.asyncio
async def test_judge_reply_maps_fail_alias(allow_unix_socket_only) -> None:
    client = _MockClient(verdict="FAIL", reasoning="no answer")
    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="nextseek_query",
        actual_route="nextseek_query",
        reply_text="",
        frames_summary="",
        baml_client=client,
    )
    assert result.verdict == VERDICT_FAIL


@pytest.mark.asyncio
async def test_judge_reply_maps_unknown_verdict_to_inconclusive(
    allow_unix_socket_only,
) -> None:
    client = _MockClient(verdict="MAYBE", reasoning="?")
    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="container_cc",
        actual_route="container_cc",
        reply_text="ok",
        frames_summary="",
        baml_client=client,
    )
    assert result.verdict == VERDICT_INCONCLUSIVE


@pytest.mark.asyncio
async def test_judge_reply_surfaces_exceptions_as_inconclusive(
    allow_unix_socket_only,
) -> None:
    """A BAML failure must NOT propagate — it becomes verdict=INCONCLUSIVE."""

    class _RaisingClient:
        async def JudgeRouterAnswer(self, *, input):  # noqa: N802
            raise RuntimeError("upstream quota exceeded")

    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="nextseek_query",
        actual_route="nextseek_query",
        reply_text="ok",
        frames_summary="",
        baml_client=_RaisingClient(),
    )
    assert result.verdict == VERDICT_INCONCLUSIVE
    assert "RuntimeError" in result.reasoning
    assert "<judge_unavailable" in result.reasoning


@pytest.mark.asyncio
async def test_judge_reply_handles_none_actual_route(
    allow_unix_socket_only,
) -> None:
    """``actual_route=None`` (transport error before route_decided) must not crash."""
    client = _MockClient(verdict="FAIL", reasoning="no route")
    result = await judge_reply(
        query_id="q",
        query_text="q",
        expected_route="nextseek_query",
        actual_route=None,
        reply_text="",
        frames_summary="error x 1",
        baml_client=client,
    )
    assert result.verdict == VERDICT_FAIL


# --- Integration with run_router_e2e module-level wiring -----------------


def test_run_router_e2e_imports_judge_module() -> None:
    """The harness must re-export judge helpers; an import-time AttributeError
    would silently route every query to ``INCONCLUSIVE`` in the wild."""
    import importlib

    mod = importlib.import_module("tools.e2e.run_router_e2e")
    assert hasattr(mod, "extract_reply_text")
    assert hasattr(mod, "judge_reply")
    assert hasattr(mod, "summarise_frames")
    assert mod.VERDICT_PASS == "PASS"
    assert mod.VERDICT_INCONCLUSIVE == "INCONCLUSIVE"


def test_query_record_has_new_judge_fields() -> None:
    """Pins the QueryRecord shape change against accidental field removal."""
    from tools.e2e.run_router_e2e import QueryRecord

    record = QueryRecord(
        query_id="x", query_text="x", expected_route="container_cc"
    )
    assert record.reply_text == ""
    assert record.semantic_verdict == "INCONCLUSIVE"
    assert record.semantic_reasoning == ""
    assert record.judge_latency_seconds == 0.0


def test_manifest_schema_version_is_two() -> None:
    """Schema bumped from 1 to 2 in Phase 7 Residual #5; pin it."""
    from dataclasses import asdict

    from tools.e2e.run_router_e2e import Manifest

    manifest = Manifest(
        schema_version=2,
        run_id="x",
        started_at="x",
        completed_at="x",
        bridge_pid=1,
        bridge_port=1,
    )
    payload = asdict(manifest)
    assert payload["schema_version"] == 2


# pytest may try to use this as a fixture if we don't anchor it explicitly.
if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
