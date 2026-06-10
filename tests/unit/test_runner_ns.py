"""T1.3 / T9 -- container/runner_ns.py unit tests.

Pins fd-shuffle correctness, JSONL envelope contract, exit codes, and
runner-side uncaught-exception handling. Redaction tests that targeted
the old chat_nextseek-backed _redact_send_event helper have been removed
(that helper is gone; the new runner translates viewset terminal dicts
directly -- see test_runner_ns_parity.py for the new behavioral tests).

CRITICAL: per locked LLM-router design spec line 387, `DMAC_RUNNER_NS_NO_REMAP=1`
MUST be set BEFORE `from container.runner_ns import ...`. We do this at module
top before the import; pytest's monkeypatch fixture is per-test and runs AFTER
module-level imports, so it cannot be used here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

# CRITICAL: env var MUST be set before importing container.runner_ns so the
# module-level remap branch is the opt-out branch (NOT the production branch).
os.environ["DMAC_RUNNER_NS_NO_REMAP"] = "1"

# Now safe to import. The module-level _EVENTS_FD will be 1 (opt-out value).
from container import runner_ns
from container.runner_ns import (  # noqa: E402 -- intentional post-env-set import
    _EVENTS_FD,
    _perform_event_channel_remap,
)


# Sanity assertion: the env var took effect and _EVENTS_FD is the opt-out value.
assert _EVENTS_FD == 1, (
    f"DMAC_RUNNER_NS_NO_REMAP was set but _EVENTS_FD = {_EVENTS_FD}, expected 1. "
    "Likely cause: production remap branch executed at import time."
)


# ---------------------------------------------------------- helpers / fixtures


@pytest.fixture
def fd_capture(capfd: pytest.CaptureFixture) -> "FdCapture":
    """Provide tempfile-backed stdout/stderr captures + restore-on-exit.

    Per locked spec line 389, the test driver opens two TemporaryFile()
    handles and binds process fd 1 / fd 2 to them. We must release pytest's
    own fd capture first (via capfd.disabled()).
    """
    return FdCapture(capfd=capfd)


class FdCapture:
    def __init__(self, capfd: pytest.CaptureFixture) -> None:
        self.capfd = capfd
        self.stdout_cap: Any | None = None
        self.stderr_cap: Any | None = None

    @contextmanager
    def active(self) -> Iterator[None]:
        """Activate tempfile-backed fd capture for the current test-call phase."""
        with self.capfd.disabled():
            self._setup()
            try:
                yield
            finally:
                self._teardown()

    def _setup(self) -> None:
        stdout_cap = tempfile.TemporaryFile()
        stderr_cap = tempfile.TemporaryFile()
        saved_1 = os.dup(1)
        saved_2 = os.dup(2)
        saved_stdout = sys.stdout
        saved_stderr = sys.stderr
        redirected_stdout = None
        redirected_stderr = None
        try:
            os.dup2(stdout_cap.fileno(), 1)
            os.dup2(stderr_cap.fileno(), 2)
            redirected_stdout = os.fdopen(1, "w", buffering=1, closefd=False)
            redirected_stderr = os.fdopen(2, "w", buffering=1, closefd=False)
            sys.stdout = redirected_stdout
            sys.stderr = redirected_stderr
            self.stdout_cap = stdout_cap
            self.stderr_cap = stderr_cap
            self._saved_1 = saved_1
            self._saved_2 = saved_2
            self._saved_stdout = saved_stdout
            self._saved_stderr = saved_stderr
            self._redirected_stdout = redirected_stdout
            self._redirected_stderr = redirected_stderr
        finally:
            if self.stdout_cap is None:
                os.dup2(saved_1, 1)
                os.dup2(saved_2, 2)
                os.close(saved_1)
                os.close(saved_2)
                stdout_cap.close()
                stderr_cap.close()

    def _teardown(self) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout = self._saved_stdout
        sys.stderr = self._saved_stderr
        if self._redirected_stdout is not None:
            self._redirected_stdout.close()
        if self._redirected_stderr is not None:
            self._redirected_stderr.close()
        os.dup2(self._saved_1, 1)
        os.dup2(self._saved_2, 2)
        os.close(self._saved_1)
        os.close(self._saved_2)

    def stdout_bytes(self) -> bytes:
        assert self.stdout_cap is not None
        self.stdout_cap.seek(0)
        return self.stdout_cap.read()

    def stderr_bytes(self) -> bytes:
        assert self.stderr_cap is not None
        self.stderr_cap.seek(0)
        return self.stderr_cap.read()


# ------------------------------------------------------- fd-shuffle correctness


def test_perform_event_channel_remap_redirects_fd1_to_fd2(fd_capture: FdCapture) -> None:
    """After _perform_event_channel_remap: fd 1 -> what fd 2 pointed at; saved fd -> what fd 1 pointed at.

    Drives the production code path explicitly under controlled fd capture.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        try:
            # `print` goes through sys.stdout which writes to fd 1 -- now redirected to stderr_cap.
            print("DIAG-x", flush=True)
            # `sys.stdout.write` same path.
            sys.stdout.write("DIAG-y")
            sys.stdout.flush()
            # `os.write(events_fd, ...)` goes to the saved fd -- still pointing at stdout_cap.
            os.write(events_fd, b"event-line\n")
        finally:
            os.close(events_fd)

    assert fd_capture.stdout_bytes() == b"event-line\n", (
        "events written via os.write(events_fd) must land ONLY on the saved stdout fd"
    )
    stderr_bytes = fd_capture.stderr_bytes()
    assert b"DIAG-x" in stderr_bytes, "print() output must land on stderr (post-remap)"
    assert b"DIAG-y" in stderr_bytes, "sys.stdout.write output must land on stderr (post-remap)"
    assert b"event-line" not in stderr_bytes, (
        "the events line must NOT appear on stderr -- that would indicate the fd-remap inverted"
    )
    assert b"DIAG-x" not in fd_capture.stdout_bytes(), (
        "print() output must NOT appear on stdout -- that would indicate the fd-remap did not take"
    )


def test_module_level_opt_out_when_env_var_set() -> None:
    """When DMAC_RUNNER_NS_NO_REMAP is set, _EVENTS_FD == 1 and no remap occurred.

    This is the opt-out path tested via the module-level state captured at
    import time (env var was set in conftest's module-top assignment above).
    """
    assert os.environ.get("DMAC_RUNNER_NS_NO_REMAP") == "1"
    assert _EVENTS_FD == 1


# ------------------------------ _has_failure_signal (still present, still tested)


def test_has_failure_signal_status_error() -> None:
    """Failure signal 1: status in {error, partial, failure}."""
    assert runner_ns._has_failure_signal({"status": "error"})
    assert runner_ns._has_failure_signal({"status": "partial"})
    assert runner_ns._has_failure_signal({"status": "failure"})
    assert not runner_ns._has_failure_signal({"status": "ok"})


def test_has_failure_signal_error_type() -> None:
    """Failure signal 2: non-empty error_type."""
    assert runner_ns._has_failure_signal({"error_type": "AUTH_FAILED"})
    assert not runner_ns._has_failure_signal({"error_type": ""})


def test_has_failure_signal_top_error() -> None:
    """Failure signal 3: truthy top-level error."""
    assert runner_ns._has_failure_signal({"error": "something went wrong"})
    assert not runner_ns._has_failure_signal({"error": ""})


def test_has_failure_signal_debug_error() -> None:
    """Failure signal 4: truthy debug.error."""
    assert runner_ns._has_failure_signal({"debug": {"error": "stack trace"}})
    assert not runner_ns._has_failure_signal({"debug": {"error": ""}})


def test_has_failure_signal_debug_fatal_error() -> None:
    """Failure signal 5: truthy debug.fatal_error."""
    assert runner_ns._has_failure_signal({"debug": {"fatal_error": "fatal"}})
    assert not runner_ns._has_failure_signal({"debug": {"fatal_error": ""}})


def test_has_failure_signal_clean_success() -> None:
    """No failure signals on a clean success terminal."""
    assert not runner_ns._has_failure_signal({"reply": "ok", "bundle_id": 1})


# ----------------------------------- no-interleave + runner-side exception path


def test_no_diagnostic_interleave_with_stubbed_client(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stubbed _build_assistant_client whose run_query prints diagnostics + returns events.

    The captured stdout MUST be byte-equal to the JSONL the runner intends --
    diagnostic prints / writes MUST land on stderr (unchanged from original test).
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    print("[DEBUG][PARSER] starting", flush=True)
                    sys.stdout.write("[GRAPH] traversing\n")
                    sys.stdout.flush()
                    return (
                        {"reply": "done", "debug": {"agent": "reporter"}, "bundle_id": None},
                        [("agent_started", {"agent": "entity"})],
                    )

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("find me PBMCs\n"))
            runner_ns.main(["--session", "test-sess"])
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    # Captured stdout MUST be exactly the 2 JSONL events (agent_started + query_complete) -- NOTHING ELSE.
    lines = stdout.strip().split(b"\n")
    assert len(lines) == 2, f"expected exactly 2 JSONL lines on stdout; got {len(lines)}: {lines}"
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1 == {"event": "agent_started", "payload": {"agent": "entity"}}
    assert e2["event"] == "query_complete"
    assert e2["payload"]["reply"] == "done"  # success-path: NOT redacted

    # Diagnostic prints MUST land on stderr (NOT stdout).
    stderr = fd_capture.stderr_bytes()
    assert b"[DEBUG][PARSER]" in stderr
    assert b"[GRAPH] traversing" in stderr
    # And MUST NOT appear on stdout.
    assert b"[DEBUG][PARSER]" not in stdout
    assert b"[GRAPH] traversing" not in stdout


def test_main_empty_stdin_emits_empty_query_error(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-T1.3-4-1 round-4 hardener: empty stdin -> `ns_runner_error` with
    `error_type: "EmptyQuery"`, sys.exit(2). This branch lives BEFORE the
    client construction call in `main()`, so no stub is required.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            monkeypatch.setattr(sys, "stdin", _FakeStdin(""))  # empty input
            with pytest.raises(SystemExit) as excinfo:
                runner_ns.main(["--session", "test-sess"])
            assert excinfo.value.code == 2
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    assert len(lines) == 1, f"expected exactly 1 JSONL line on stdout; got {lines}"
    event = json.loads(lines[0])
    assert event == {"event": "ns_runner_error", "payload": {"error_type": "EmptyQuery"}}


def test_runner_uncaught_exception_emits_ns_runner_error_type_name_only(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locked spec lines 493, 568: uncaught exception -> ns_runner_error with error_type only.

    NEVER str(exc), NEVER repr(exc), NEVER exc.args. The exception class name
    via type(exc).__name__ is the ONLY payload field.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    raise RuntimeError(
                        "inner failure with AWS_BEARER_TOKEN_BEDROCK=top-secret-token in message"
                    )

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("trigger failure\n"))

            with pytest.raises(SystemExit) as excinfo:
                runner_ns.main(["--session", "test-sess"])
            assert excinfo.value.code != 0
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    # Inspect captured stdout: the ns_runner_error line carrying ONLY the type name.
    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    assert len(lines) >= 1, f"expected at least 1 JSONL line on stdout; got {lines}"
    error_lines = [json.loads(ln) for ln in lines if json.loads(ln).get("event") == "ns_runner_error"]
    assert len(error_lines) == 1, f"expected exactly 1 ns_runner_error event; got {error_lines}"
    err = error_lines[0]
    assert err["payload"] == {"error_type": "RuntimeError"}, (
        f"ns_runner_error payload must be type name only; got {err['payload']}"
    )
    # And the credential MUST NOT appear anywhere in the captured stdout.
    assert b"AWS_BEARER_TOKEN_BEDROCK" not in stdout
    assert b"top-secret-token" not in stdout
    assert b"inner failure" not in stdout  # no str(exc) leak


# ------------------------------- synthetic terminal fallback (locked spec L107)


def test_main_emits_synthetic_query_complete_when_stream_ends_without_terminal(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the viewset stream ends without a terminal event, the client returns
    the sentinel {"__error__": "stream ended without terminal event", "agent": None}.
    The runner MUST emit a failure-shaped query_complete with
    error_type='RunnerSyntheticTerminal' (not a bare query_error).
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    # Exactly the sentinel the real AssistantClient emits on stream close
                    return (
                        {"__error__": "stream ended without terminal event", "agent": None},
                        [("agent_started", {"agent": "entity"})],
                    )

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("find me PBMCs\n"))
            exit_code = runner_ns.main(["--session", "test-sess"])
            assert exit_code == 0, (
                "synthetic terminal is informational, not a runner failure"
            )
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    parsed = [json.loads(ln) for ln in lines]
    event_names = [e["event"] for e in parsed]

    # agent_started is forwarded, then synthetic query_complete
    assert "agent_started" in event_names
    assert "query_complete" in event_names

    synthetic = [e for e in parsed if e["event"] == "query_complete"][0]
    payload = synthetic["payload"]
    assert payload.get("error_type") == "RunnerSyntheticTerminal", (
        f"synthetic query_complete payload must carry "
        f"error_type='RunnerSyntheticTerminal'; got payload={payload}"
    )
    assert payload.get("status") in {"error", "partial", "failure"}, (
        f"synthetic query_complete must carry a failure status; "
        f"got status={payload.get('status')!r}"
    )


def test_main_does_not_emit_duplicate_terminal_on_clean_success(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative guard: clean success returns exactly one query_complete terminal.

    The synthetic terminal must NOT fire when the client returns a clean terminal.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    return (
                        {"reply": "done", "debug": {"agent": "reporter"}, "bundle_id": None},
                        [],
                    )

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("normal turn\n"))
            runner_ns.main(["--session", "test-sess"])
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    parsed = [json.loads(ln) for ln in lines]
    terminals = [e for e in parsed if e["event"] in ("query_complete", "query_error")]
    assert len(terminals) == 1, (
        f"expected exactly ONE terminal event; got {len(terminals)}: {terminals}"
    )
    assert terminals[0]["payload"].get("error_type") != "RunnerSyntheticTerminal", (
        "synthetic terminal must NOT fire when client returned a clean terminal"
    )


def test_main_does_not_emit_synthetic_when_query_error(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative guard: genuine query_error (non-None agent) must NOT produce a synthetic terminal.

    The runner translates a genuine query_error terminal to a query_error event,
    not a synthetic query_complete.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    # Genuine query_error -- non-None agent
                    return (
                        {"__error__": "LLMFatalError text", "agent": "graph", "session_id": None},
                        [],
                    )

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("error turn\n"))
            runner_ns.main(["--session", "test-sess"])
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    parsed = [json.loads(ln) for ln in lines]
    synthetic = [
        e for e in parsed
        if e["event"] == "query_complete"
        and e["payload"].get("error_type") == "RunnerSyntheticTerminal"
    ]
    assert synthetic == [], (
        f"synthetic terminal must NOT fire for a genuine query_error; got: {synthetic}"
    )
    # Must emit query_error (not query_complete) for genuine query_error
    qe_events = [e for e in parsed if e["event"] == "query_error"]
    assert len(qe_events) == 1


# ----------------------------- AUTH_FAILED and TRANSPORT_ERROR (carry-forward)


def test_auth_failed_emits_failure_shaped_query_complete(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewset 401 -> failure-shaped query_complete with error_type AUTH_FAILED.

    The runner must catch httpx.HTTPStatusError on 401 and emit a typed failure
    that the bridge routes to ns_query_complete_with_error. Credentials must
    never appear in the emitted payload.
    """
    import httpx

    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    resp = httpx.Response(401, request=httpx.Request("POST", "https://ns.example/query/"))
                    raise httpx.HTTPStatusError("401", request=resp.request, response=resp)

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("find samples\n"))
            with pytest.raises(SystemExit) as excinfo:
                runner_ns.main(["--session", "test-sess"])
            assert excinfo.value.code == 1
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    parsed = [json.loads(ln) for ln in lines]
    qc = [e for e in parsed if e["event"] == "query_complete"]
    assert qc, "must emit query_complete on 401"
    assert qc[0]["payload"]["error_type"] == "AUTH_FAILED"
    assert qc[0]["payload"]["status"] == "error"
    assert "secret" not in stdout.decode()


def test_transport_error_emits_failure_shaped_query_complete(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx.TransportError -> failure-shaped query_complete with error_type TRANSPORT_ERROR."""
    import httpx

    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            class FakeClient:
                def run_query(self, q, *, mode, session_id=None, **k):
                    raise httpx.ConnectError("connection refused")

            monkeypatch.setattr(runner_ns, "_build_assistant_client", lambda: FakeClient())
            monkeypatch.setattr(sys, "stdin", _FakeStdin("find samples\n"))
            with pytest.raises(SystemExit) as excinfo:
                runner_ns.main(["--session", "test-sess"])
            assert excinfo.value.code == 1
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    parsed = [json.loads(ln) for ln in lines]
    qc = [e for e in parsed if e["event"] == "query_complete"]
    assert qc, "must emit query_complete on TransportError"
    assert qc[0]["payload"]["error_type"] == "TRANSPORT_ERROR"
    assert qc[0]["payload"]["status"] == "error"


# ---------------------------------------------------------- _FakeStdin helper


class _FakeStdin:
    def __init__(self, line: str) -> None:
        self._line = line
        self._consumed = False

    def readline(self) -> str:
        if self._consumed:
            return ""
        self._consumed = True
        return self._line
