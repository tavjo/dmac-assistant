"""Tests for _assistant_client.AssistantClient -- async polling transport (A-3).

Transport: POST query/async/ -> 202 AsyncQueryResponse, then
GET tasks/{task_id}/progress/ polling until a terminal event appears.
Public contract (run_query signature + (terminal, events) return shapes) is
unchanged so T8 plugin runner is unaffected.
"""
import pathlib
import sys

import httpx
import pytest

_BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
sys.path.insert(0, str(_BIN))
import _assistant_client as c

# ---------------------------------------------------------------------------
# Helpers for building mock HTTP responses
# ---------------------------------------------------------------------------

_TASK_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _async_202() -> httpx.Response:
    return httpx.Response(202, json={"task_id": _TASK_ID, "session_id": _SESSION_ID})


def _progress(status: str, events: list[dict], result: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json={
        "task_id": _TASK_ID,
        "session_id": _SESSION_ID,
        "status": status,
        "progress": events,
        "result": result,
    })


def _make_seq_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    """Return a MockTransport that serves responses in order: first call -> responses[0], etc."""
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return next(it)

    return httpx.MockTransport(handler)


import contextlib


@contextlib.contextmanager
def _no_real_sleep(recorder: list[float]):
    """Replace module-level _sleep with a recorder so retries never sleep for real."""
    original = c._sleep
    c._sleep = recorder.append  # records the requested duration, sleeps 0
    try:
        yield
    finally:
        c._sleep = original


def _client(transport: httpx.BaseTransport, timeout: float = 300.0, poll_interval: float = 0.0) -> c.AssistantClient:
    return c.AssistantClient(
        base_url="https://ns.example",
        assistant_prefix="nextseek_api/assistant",
        auth=("u", "p"),
        transport=transport,
        timeout=timeout,
        poll_interval=poll_interval,
    )


# ---------------------------------------------------------------------------
# (a) on_event fires incrementally in order with no duplicates across polls
# ---------------------------------------------------------------------------

def test_on_event_fires_incrementally_no_duplicates():
    """Three polls: poll1 delivers agent_started; poll2 delivers +agent_complete;
    poll3 delivers +query_complete.  on_event must fire exactly once per event,
    in order, with no duplicates.
    """
    responses = [
        _async_202(),
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
        ]),
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "agent_complete", "data": {"agent": "entity"}},
        ]),
        _progress("completed", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "agent_complete", "data": {"agent": "entity"}},
            {"event": "query_complete", "data": {"reply": "hello", "session_id": _SESSION_ID}},
        ]),
    ]
    fired: list[tuple[str, dict]] = []
    terminal, events = _client(_make_seq_transport(responses)).run_query(
        "find samples", mode="standard", on_event=lambda n, d: fired.append((n, d))
    )
    assert [name for name, _ in fired] == ["agent_started", "agent_complete", "query_complete"]
    assert fired[0][1]["agent"] == "entity"
    assert fired[2][1]["reply"] == "hello"
    assert terminal["reply"] == "hello"
    assert len(events) == 3


# ---------------------------------------------------------------------------
# (b) (terminal, events) matches the old SSE shapes exactly
# ---------------------------------------------------------------------------

def test_run_query_terminal_and_events_shapes():
    """Terminal dict and events list must match the shapes the SSE version produced."""
    responses = [
        _async_202(),
        _progress("completed", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "query_complete", "data": {"reply": "hello", "session_id": "s1"}},
        ]),
    ]
    terminal, events = _client(_make_seq_transport(responses)).run_query(
        "find samples", mode="standard"
    )
    assert terminal["reply"] == "hello"
    assert any(e[0] == "agent_started" for e in events)
    assert any(e[0] == "query_complete" for e in events)


# ---------------------------------------------------------------------------
# (c) query_error path
# ---------------------------------------------------------------------------

def test_run_query_error_event_terminal():
    """query_error in progress -> terminal with __error__ key matching old SSE shape."""
    responses = [
        _async_202(),
        _progress("error", [
            {"event": "query_error", "data": {"error": "boom", "agent": "entity", "session_id": "s1"}},
        ], result={"error": "boom", "agent": "entity", "session_id": "s1"}),
    ]
    terminal, _ = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert terminal["__error__"] == "boom"
    assert terminal["agent"] == "entity"


# ---------------------------------------------------------------------------
# (d) 401 on the async POST raises httpx.HTTPStatusError
# ---------------------------------------------------------------------------

def test_run_query_401_raises_http_status_error():
    """A 401 on the POST query/async/ must raise httpx.HTTPStatusError (T8/T9 AUTH_FAILED mapping)."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(401, request=r)
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _client(transport).run_query("x", mode="standard")
    assert exc_info.value.response.status_code == 401


# ---------------------------------------------------------------------------
# (e) status=completed with result but NO terminal event in progress -> fallback
# ---------------------------------------------------------------------------

def test_status_completed_result_fallback_no_terminal_event():
    """If status becomes 'completed' but no terminal event in progress, fall back to result."""
    result_data = {"reply": "fallback reply", "session_id": "s1"}
    responses = [
        _async_202(),
        _progress("completed", [], result=result_data),
    ]
    terminal, events = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert terminal["reply"] == "fallback reply"
    assert events == []


# ---------------------------------------------------------------------------
# (f) status=error with result -> query_error-shaped terminal
# ---------------------------------------------------------------------------

def test_status_error_result_fallback():
    """status=error + result dict (but no progress events) -> __error__ terminal shape."""
    result_data = {"error": "task error", "agent": "entity", "session_id": "s1"}
    responses = [
        _async_202(),
        _progress("error", [], result=result_data),
    ]
    terminal, _ = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert "__error__" in terminal
    assert terminal["agent"] == "entity"


# ---------------------------------------------------------------------------
# (g) deadline exceeded -> sentinel terminal (monkeypatched sleep/clock)
# ---------------------------------------------------------------------------

def test_deadline_exceeded_returns_sentinel(monkeypatch):
    """When total elapsed time exceeds timeout, stop polling and return the sentinel terminal."""
    # Use a fake clock that jumps past the timeout on the first poll
    _time = [0.0]

    def fake_monotonic():
        return _time[0]

    def fake_sleep(s):
        _time[0] += 400.0  # jump past any realistic timeout

    monkeypatch.setattr(c, "_monotonic", fake_monotonic)
    monkeypatch.setattr(c, "_sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        # progress endpoint never delivers a terminal -- but the deadline fires first
        return _progress("running", [])

    client = _client(httpx.MockTransport(handler), timeout=1.0, poll_interval=0.0)
    terminal, _ = client.run_query("x", mode="standard")
    assert "stream ended without terminal event" in terminal["__error__"]
    assert terminal["agent"] is None


# ---------------------------------------------------------------------------
# (h) omitting on_event works (no callback)
# ---------------------------------------------------------------------------

def test_on_event_omitted_works():
    """run_query must work correctly when on_event is not supplied."""
    responses = [
        _async_202(),
        _progress("completed", [
            {"event": "query_complete", "data": {"reply": "ok", "session_id": "s1"}},
        ]),
    ]
    terminal, events = _client(_make_seq_transport(responses)).run_query(
        "find samples", mode="standard"
    )
    assert terminal["reply"] == "ok"
    assert len(events) == 1


# ---------------------------------------------------------------------------
# (i) on_event callback exception propagates (not swallowed)
# ---------------------------------------------------------------------------

def test_on_event_exception_propagates():
    """Exceptions from the on_event callback must propagate, not be swallowed."""
    responses = [
        _async_202(),
        _progress("completed", [
            {"event": "query_complete", "data": {"reply": "ok"}},
        ]),
    ]

    def bad_callback(name, data):
        raise ValueError("callback failure")

    with pytest.raises(ValueError, match="callback failure"):
        _client(_make_seq_transport(responses)).run_query(
            "x", mode="standard", on_event=bad_callback
        )


# ---------------------------------------------------------------------------
# (j) session_detail, download_bundle, download_artifact still work
# ---------------------------------------------------------------------------

def test_session_detail_and_downloads():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions/s1/"):
            return httpx.Response(200, json={
                "session_id": "11111111-1111-4111-8111-111111111111",
                "created_at": "2026-06-09T00:00:00Z",
                "query_count": 1,
                "has_results": True,
            })
        if "/bundles/2/" in request.url.path and "/artifacts/" not in request.url.path:
            return httpx.Response(200, json={"bundle_id": 2})
        if request.url.path.endswith("/artifacts/key/"):
            return httpx.Response(200, content=b"payload")
        raise AssertionError(f"unexpected path {request.url.path}")

    client = _client(httpx.MockTransport(handler))
    detail = client.session_detail("s1", include_turns=False)
    assert detail["query_count"] == 1
    assert client.download_bundle("s1", 2)["bundle_id"] == 2
    assert client.download_artifact("s1", 2, "key") == b"payload"


# ---------------------------------------------------------------------------
# (k) _iter_sse deleted -- no reference to dead function
# ---------------------------------------------------------------------------

def test_iter_sse_deleted():
    """_iter_sse must not exist on the module after the SSE transport is gone."""
    assert not hasattr(c, "_iter_sse"), "_iter_sse is dead code and must be removed"


# ---------------------------------------------------------------------------
# (l) session_id and force_new pass through to the async POST body
# ---------------------------------------------------------------------------

def test_run_query_passes_session_id_and_force_new():
    """session_id and force_new must appear in the POST query/async/ body."""
    captured_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json as _json
            captured_body.update(_json.loads(request.content))
            return _async_202()
        return _progress("completed", [
            {"event": "query_complete", "data": {"reply": "ok"}},
        ])

    _client(httpx.MockTransport(handler)).run_query(
        "test q", mode="plan", session_id=_SESSION_ID, force_new=True
    )
    assert captured_body["mode"] == "plan"
    assert captured_body["session_id"] == _SESSION_ID
    assert captured_body["force_new"] is True


# ---------------------------------------------------------------------------
# (m) non-terminal events do not stop polling
# ---------------------------------------------------------------------------

def test_non_terminal_events_do_not_stop_polling():
    """Polling must continue until a terminal event is seen even if other events arrive."""
    responses = [
        _async_202(),
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
        ]),
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "agent_complete", "data": {"agent": "entity"}},
        ]),
        _progress("completed", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "agent_complete", "data": {"agent": "entity"}},
            {"event": "query_complete", "data": {"reply": "done"}},
        ]),
    ]
    terminal, events = _client(_make_seq_transport(responses)).run_query(
        "find samples", mode="standard"
    )
    assert terminal["reply"] == "done"
    assert len(events) == 3


# ---------------------------------------------------------------------------
# (n) result=None/empty on terminal status -> sentinel
# ---------------------------------------------------------------------------

def test_status_completed_no_result_returns_sentinel():
    """status=completed, no terminal events, result=None -> stream-ended sentinel."""
    responses = [
        _async_202(),
        _progress("completed", [], result=None),
    ]
    terminal, _ = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert "stream ended without terminal event" in terminal["__error__"]
    assert terminal["agent"] is None


# ---------------------------------------------------------------------------
# (o) STREAM_ENDED_SENTINEL constant is exported and matches sentinel string
# ---------------------------------------------------------------------------

def test_stream_ended_sentinel_constant():
    """STREAM_ENDED_SENTINEL must be exported and equal to the sentinel embedded in terminals."""
    assert hasattr(c, "STREAM_ENDED_SENTINEL")
    assert c.STREAM_ENDED_SENTINEL == "stream ended without terminal event"
    # The deadline-exceeded path must use the constant.
    responses = [
        _async_202(),
        _progress("completed", [], result=None),
    ]
    terminal, _ = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert terminal["__error__"] == c.STREAM_ENDED_SENTINEL


# ---------------------------------------------------------------------------
# (p) timeout and request_timeout are distinct knobs
# ---------------------------------------------------------------------------

def test_timeout_and_request_timeout_are_distinct_knobs():
    """The total polling deadline (timeout) and per-request httpx timeout (request_timeout)
    must be independently configurable. Confirm both attributes survive construction."""
    cl = c.AssistantClient(
        base_url="https://ns.example",
        assistant_prefix="nextseek_api/assistant",
        auth=("u", "p"),
        timeout=600.0,
        request_timeout=10.0,
    )
    assert cl._timeout == 600.0
    assert cl._request_timeout == 10.0
    assert cl._timeout != cl._request_timeout


# ---------------------------------------------------------------------------
# (q) null error field does not yield the string "None"
# ---------------------------------------------------------------------------

def test_status_error_null_error_field_does_not_yield_string_none():
    """When status=error and result.error is null/None, the __error__ terminal must
    contain the fallback message, NOT the string 'None'."""
    result_data = {"error": None, "agent": "entity", "session_id": "s1"}
    responses = [
        _async_202(),
        _progress("error", [], result=result_data),
    ]
    terminal, _ = _client(_make_seq_transport(responses)).run_query("x", mode="standard")
    assert "__error__" in terminal
    assert terminal["__error__"] != "None"
    assert terminal["__error__"] == "task ended with status=error"


# ---------------------------------------------------------------------------
# (r) mid-task poll GET failure propagates out of run_query
# ---------------------------------------------------------------------------

def test_mid_task_poll_transport_error_propagates():
    """If the POST succeeds but EVERY progress GET raises a transport error,
    run_query retries the idempotent GET up to _PROGRESS_GET_MAX_RETRIES times
    and, with all attempts exhausted before the deadline, surfaces the transport
    error (task-13R3 bounded retry; runner_ns maps it to TRANSPORT_ERROR).

    Updated from the W3 fail-fast pin: transient stalls are now retried, but an
    exhausted retry budget still surfaces the failure rather than masking it.
    """
    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        call_count[0] += 1
        raise httpx.ConnectError("connection refused during poll")

    sleeps: list[float] = []
    with _no_real_sleep(sleeps):
        with pytest.raises(httpx.TransportError):
            _client(httpx.MockTransport(handler)).run_query("x", mode="standard")
    # All retry attempts were made before surfacing the failure.
    assert call_count[0] == c._PROGRESS_GET_MAX_RETRIES, (
        "poll GET must be retried the full bounded budget before surfacing"
    )
    # Backoff used the injectable _sleep (one fewer sleep than attempts).
    assert len(sleeps) == c._PROGRESS_GET_MAX_RETRIES - 1


# ---------------------------------------------------------------------------
# (s) progress-shrinkage guard raises RuntimeError
# ---------------------------------------------------------------------------

def test_progress_shrinkage_raises_runtime_error():
    """If the progress list shrinks between polls (server restart / task eviction),
    run_query must raise RuntimeError with a clear message."""
    responses = [
        _async_202(),
        # First poll: 2 events
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "agent_complete", "data": {"agent": "entity"}},
        ]),
        # Second poll: progress list shrank to 1 event (server restart)
        _progress("running", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
        ]),
    ]
    with pytest.raises(RuntimeError, match="progress list shrank"):
        _client(_make_seq_transport(responses)).run_query("x", mode="standard")


# ---------------------------------------------------------------------------
# (t) task-13R3: bounded retry on the idempotent progress GET
# ---------------------------------------------------------------------------

def test_progress_get_retries_then_succeeds():
    """Test 1: ReadTimeout on the progress GET N times, then a valid terminal
    progress response -> run_query RETRIES and ultimately SUCCEEDS. No duplicate
    events (seen_count slice dedups the recovered response)."""
    n_fail = c._PROGRESS_GET_MAX_RETRIES - 1  # transient: fewer than the budget
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        state["gets"] += 1
        if state["gets"] <= n_fail:
            raise httpx.ReadTimeout("progress GET stalled")
        return _progress("completed", [
            {"event": "agent_started", "data": {"agent": "entity", "mode": ""}},
            {"event": "query_complete", "data": {"reply": "recovered", "session_id": _SESSION_ID}},
        ])

    fired: list[tuple[str, dict]] = []
    sleeps: list[float] = []
    with _no_real_sleep(sleeps):
        terminal, events = _client(httpx.MockTransport(handler)).run_query(
            "x", mode="standard", on_event=lambda nm, d: fired.append((nm, d))
        )
    assert terminal["reply"] == "recovered"
    # Exactly one query_complete -- no duplicates from the retried GET.
    assert [name for name, _ in events] == ["agent_started", "query_complete"]
    assert [name for name, _ in fired] == ["agent_started", "query_complete"]
    assert state["gets"] == n_fail + 1
    assert len(sleeps) == n_fail  # one backoff sleep per failed attempt


def test_progress_get_retries_exhausted_surfaces_transport_failure():
    """Test 2: ReadTimeout on EVERY progress GET until retries exhaust ->
    run_query surfaces the transport failure (re-raise), NOT a success and NOT
    a misleading query_complete-with-error."""
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        state["gets"] += 1
        raise httpx.ReadTimeout("progress GET always stalls")

    sleeps: list[float] = []
    with _no_real_sleep(sleeps):
        with pytest.raises(httpx.TimeoutException):
            _client(httpx.MockTransport(handler)).run_query("x", mode="standard")
    assert state["gets"] == c._PROGRESS_GET_MAX_RETRIES
    assert len(sleeps) == c._PROGRESS_GET_MAX_RETRIES - 1


def test_progress_get_http_status_error_not_retried():
    """Test 3: a 4xx/5xx HTTPStatusError on the progress GET still propagates and
    is NOT retried (transport-vs-status distinction)."""
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        state["gets"] += 1
        return httpx.Response(503, json={"detail": "service unavailable"})

    sleeps: list[float] = []
    with _no_real_sleep(sleeps):
        with pytest.raises(httpx.HTTPStatusError):
            _client(httpx.MockTransport(handler)).run_query("x", mode="standard")
    assert state["gets"] == 1, "HTTPStatusError must NOT be retried"
    assert sleeps == [], "no backoff sleeps on a status error"


def test_progress_get_retry_never_exceeds_deadline():
    """Test 4: backoff uses the injectable _sleep (no real sleeping) and retries
    never exceed the _monotonic deadline -- once the deadline is crossed during
    retries, run_query stops retrying and returns the stream-ended sentinel."""
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _async_202()
        state["gets"] += 1
        raise httpx.ReadTimeout("stall")

    # Injectable monotonic clock: POST sets deadline at t0+timeout; advance the
    # clock past the deadline after the first GET attempt so the retry loop's
    # deadline check trips before exhausting the retry budget.
    ticks = iter([0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0])

    orig_monotonic = c._monotonic
    orig_sleep = c._sleep
    sleeps: list[float] = []
    c._monotonic = lambda: next(ticks)
    c._sleep = sleeps.append
    try:
        terminal, events = _client(
            httpx.MockTransport(handler), timeout=10.0
        ).run_query("x", mode="standard")
    finally:
        c._monotonic = orig_monotonic
        c._sleep = orig_sleep

    # Deadline crossed mid-retry -> stream-ended sentinel terminal, not a raise.
    assert terminal == {"__error__": c.STREAM_ENDED_SENTINEL, "agent": None}
    # Stopped well before the full retry budget (deadline ceiling honored).
    assert state["gets"] < c._PROGRESS_GET_MAX_RETRIES
