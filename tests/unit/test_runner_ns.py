"""T1.3 — container/runner_ns.py unit tests.

Pins fd-shuffle correctness, runner-side redaction across all 5 failure signals,
no-diagnostic-interleave guarantee, and runner-side uncaught-exception handling.

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
from container.runner_ns import (  # noqa: E402 — intentional post-env-set import
    _EVENTS_FD,
    _perform_event_channel_remap,
    _redact_send_event,
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
            # `print` goes through sys.stdout which writes to fd 1 — now redirected to stderr_cap.
            print("DIAG-x", flush=True)
            # `sys.stdout.write` same path.
            sys.stdout.write("DIAG-y")
            sys.stdout.flush()
            # `os.write(events_fd, ...)` goes to the saved fd — still pointing at stdout_cap.
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
        "the events line must NOT appear on stderr — that would indicate the fd-remap inverted"
    )
    assert b"DIAG-x" not in fd_capture.stdout_bytes(), (
        "print() output must NOT appear on stdout — that would indicate the fd-remap did not take"
    )


def test_module_level_opt_out_when_env_var_set() -> None:
    """When DMAC_RUNNER_NS_NO_REMAP is set, _EVENTS_FD == 1 and no remap occurred.

    This is the opt-out path tested via the module-level state captured at
    import time (env var was set in conftest's module-top assignment above).
    """
    assert os.environ.get("DMAC_RUNNER_NS_NO_REMAP") == "1"
    assert _EVENTS_FD == 1


# ------------------------------------------------- redaction across 5 signals


def test_redact_query_error_redacts_error_field() -> None:
    """Failure signal #1: payload["error"] on query_error → "<redacted>"."""
    payload = {"error": "AWS_BEARER_TOKEN_BEDROCK=secret", "agent": "parser"}
    _redact_send_event("query_error", payload)
    assert payload["error"] == "<redacted>"
    assert "AWS_BEARER_TOKEN_BEDROCK" not in json.dumps(payload)
    assert "secret" not in json.dumps(payload)
    # `agent` field is NOT a failure signal and must NOT be redacted — T2.4's adapter
    # uses it for the allow-list.
    assert payload["agent"] == "parser"


def test_query_error_emits_ns_runner_error_type_post_event(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locked spec line 486 + F-T1.3-1-3 round-1 hardener: on query_error,
    the redacting closure emits a SECOND JSONL line `ns_runner_error_type`
    carrying `{agent, error_type: "RedactedByRunner"}`. The bridge maps this
    to a DEBUG log only, never to a WS frame — but the runner MUST emit it.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            send_event = runner_ns._make_redacting_send_event()
            send_event("query_error", {"error": "credential leak text", "agent": "graph"})
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    # Expect EXACTLY two lines: the redacted query_error, then ns_runner_error_type.
    assert len(lines) == 2, f"expected 2 JSONL lines on stdout; got {len(lines)}: {lines}"
    e1 = json.loads(lines[0])
    e2 = json.loads(lines[1])
    assert e1["event"] == "query_error"
    assert e1["payload"]["error"] == "<redacted>"
    assert e1["payload"]["agent"] == "graph"
    assert "credential leak text" not in stdout.decode("utf-8")  # main field redacted
    # Second line: ns_runner_error_type with known-safe agent + sentinel error_type.
    assert e2 == {
        "event": "ns_runner_error_type",
        "payload": {"agent": "graph", "error_type": "RedactedByRunner"},
    }


def test_redact_query_complete_does_not_emit_ns_runner_error_type(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """query_complete does NOT trigger the ns_runner_error_type post-event line.

    Spec line 486 scopes the post-event emission to query_error only. A future
    regression that fires ns_runner_error_type on query_complete would mis-count
    the runner's terminal-event signaling and confuse the bridge's per-turn
    `terminal_emitted` flag.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            send_event = runner_ns._make_redacting_send_event()
            send_event(
                "query_complete",
                {"reply": "ok", "debug": {"agent": "reporter"}, "bundle_id": None},
            )
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    stdout = fd_capture.stdout_bytes()
    lines = [ln for ln in stdout.strip().split(b"\n") if ln]
    # Expect exactly ONE line — the query_complete itself. No post-event line.
    assert len(lines) == 1, f"expected 1 JSONL line on stdout; got {len(lines)}: {lines}"
    e1 = json.loads(lines[0])
    assert e1["event"] == "query_complete"
    assert b"ns_runner_error_type" not in stdout


def test_redact_query_complete_redacts_debug_error() -> None:
    """Failure signal #4: payload["debug"]["error"] non-empty → "<redacted>"; reply also redacted."""
    payload = {
        "reply": "Error: NEXTSEEK_PASSWORD=hunter2",
        "error": "legacy top-level error flag",
        "debug": {"error": "stack trace including hunter2"},
        "bundle_id": None,
    }
    _redact_send_event("query_complete", payload)
    assert payload["debug"]["error"] == "<redacted>"
    assert payload["reply"] == "<redacted; see ns_query_complete_with_error frame>"
    assert payload["error"] == "legacy top-level error flag"
    serialized = json.dumps(payload)
    assert "hunter2" not in serialized
    assert "NEXTSEEK_PASSWORD" not in serialized


def test_redact_query_complete_redacts_debug_fatal_error() -> None:
    """Failure signal #5 — LLMFatalError-shaped: debug.fatal_error + reply both redacted.

    Per locked spec line 489 + 498, the run_query LLMFatalError path (orchestrator.py:837-844)
    puts str(fatal) in BOTH debug.fatal_error AND a credentialed reply text.
    """
    payload = {
        "reply": "**The request could not be completed.**\n\nAWS_BEARER_TOKEN_BEDROCK=top-secret-token",
        "debug": {
            "fatal_error": "AWS_BEARER_TOKEN_BEDROCK=top-secret-token",
            "agent": "parser",
        },
        "bundle_id": None,
    }
    _redact_send_event("query_complete", payload)
    assert payload["debug"]["fatal_error"] == "<redacted>"
    assert payload["reply"] == "<redacted; see ns_query_complete_with_error frame>"
    assert payload["debug"]["agent"] == "parser"  # agent allow-list value NOT redacted
    serialized = json.dumps(payload)
    assert "AWS_BEARER_TOKEN_BEDROCK" not in serialized
    assert "top-secret-token" not in serialized


def test_redact_query_complete_redacts_on_status_failure() -> None:
    """Failure signal #1: payload["status"] in {"error","partial","failure"} → reply redacted."""
    payload = {
        "reply": "NEXTSEEK_PASSWORD=hunter2 leaked here",
        "status": "error",
        "bundle_id": None,
    }
    _redact_send_event("query_complete", payload)
    assert payload["reply"] == "<redacted; see ns_query_complete_with_error frame>"
    assert payload["status"] == "error"  # status itself is a flag, not a credential — keep it
    assert "hunter2" not in json.dumps(payload)


def test_redact_query_complete_redacts_on_error_type_set() -> None:
    """Failure signal #2: payload["error_type"] non-empty → reply redacted."""
    payload = {
        "reply": "secret in here NEXTSEEK_PASSWORD=hunter2",
        "error_type": "LLMTimeout",
        "bundle_id": None,
    }
    _redact_send_event("query_complete", payload)
    assert payload["reply"] == "<redacted; see ns_query_complete_with_error frame>"
    assert payload["error_type"] == "LLMTimeout"  # type name NOT redacted (known-safe enum-like)
    assert "hunter2" not in json.dumps(payload)


def test_redact_query_complete_success_path_no_redaction() -> None:
    """Success-shaped query_complete: NO failure signals → NO redaction."""
    payload = {
        "reply": "Here are the 14 samples you requested: ...",
        "debug": {"agent": "reporter"},
        "bundle_id": "bundle-xyz",
    }
    _redact_send_event("query_complete", payload)
    # NO redaction on success path.
    assert payload["reply"].startswith("Here are the 14 samples")
    assert payload["debug"]["agent"] == "reporter"
    assert payload["bundle_id"] == "bundle-xyz"


# ----------------------------------- no-interleave + runner-side exception path


def test_no_diagnostic_interleave_with_stubbed_run_query(
    fd_capture: FdCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locked spec line 567: stubbed run_query whose body prints diagnostics + emits events.

    The captured stdout MUST be byte-equal to the JSONL the runner intends —
    diagnostic prints / writes MUST land on stderr.
    """
    # 1. Drive the production remap explicitly (we set DMAC_RUNNER_NS_NO_REMAP at module top,
    #    so we have to manually invoke the remap inside this test).
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            # 2a. Stub _build_chat_nextseek_session_and_config (per F-T1.3-3-2 round-3 hardener):
            # main() calls _build_chat_nextseek_session_and_config BEFORE _run_chat_nextseek_run_query.
            # Without this stub, the unpatched helper would execute `from chat_nextseek.config import
            # ChatConfig` on host Python 3.12 where chat_nextseek is not installed (memory
            # feedback_chat_nextseek_host_image_split.md), raising ModuleNotFoundError before the
            # patched run_query is reached.
            def fake_build(session_id: str) -> tuple[object, object]:
                return object(), object()  # sentinel session + config; fake_run_query ignores them

            monkeypatch.setattr(
                runner_ns,
                "_build_chat_nextseek_session_and_config",
                fake_build,
                raising=True,
            )

            # 2b. Stub chat_nextseek's run_query: prints diagnostics, then emits 2 events.
            def fake_run_query(
                session: object,
                config: object,
                user_text: str,
                *,
                send_event: Any = None,
                credentials: dict[str, str] | None = None,
            ) -> dict[str, None]:
                print("[DEBUG][PARSER] starting", flush=True)
                sys.stdout.write("[GRAPH] traversing\n")
                sys.stdout.flush()
                send_event("agent_started", {"agent": "entity"})
                send_event(
                    "query_complete",
                    {"reply": "done", "debug": {"agent": "reporter"}, "bundle_id": None},
                )
                return {"bundle_id": None}

            monkeypatch.setattr(
                runner_ns, "_run_chat_nextseek_run_query", fake_run_query, raising=True
            )

            # 3. Invoke main() with a fake stdin (one-line query).
            monkeypatch.setattr(sys, "stdin", _FakeStdin("find me PBMCs\n"))
            runner_ns.main(["--session", "test-sess"])
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    # 4. Inspect captures.
    stdout = fd_capture.stdout_bytes()
    # Captured stdout MUST be exactly the 2 JSONL events (in emission order) — NOTHING ELSE.
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
    """F-T1.3-4-1 round-4 hardener: empty stdin → `ns_runner_error` with
    `error_type: "EmptyQuery"`, sys.exit(2). This branch lives BEFORE the
    `_build_chat_nextseek_session_and_config` call in `main()`, so no stub
    of the deferred-import helpers is required.
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
    """Locked spec lines 493, 568: uncaught exception → ns_runner_error with error_type only.

    NEVER str(exc), NEVER repr(exc), NEVER exc.args. The exception class name
    via type(exc).__name__ is the ONLY payload field.
    """
    with fd_capture.active():
        events_fd = _perform_event_channel_remap()
        monkeypatch.setattr(runner_ns, "_EVENTS_FD", events_fd, raising=True)
        try:
            # Stub _build_chat_nextseek_session_and_config (per F-T1.3-3-2 round-3 hardener)
            # so it does NOT trigger the deferred chat_nextseek import on host Python 3.12.
            # main() calls this helper FIRST; without the stub, ModuleNotFoundError would fire
            # before fake_run_query is ever reached, and the test's assertion that error_type
            # is "RuntimeError" would fail with "ModuleNotFoundError" instead.
            def fake_build(session_id: str) -> tuple[object, object]:
                return object(), object()

            monkeypatch.setattr(
                runner_ns,
                "_build_chat_nextseek_session_and_config",
                fake_build,
                raising=True,
            )

            # Stub run_query to raise an exception whose message contains a fake credential.
            def fake_run_query(
                session: object,
                config: object,
                user_text: str,
                *,
                send_event: Any = None,
                credentials: dict[str, str] | None = None,
            ) -> None:
                raise RuntimeError(
                    "inner failure with AWS_BEARER_TOKEN_BEDROCK=top-secret-token in message"
                )

            monkeypatch.setattr(
                runner_ns, "_run_chat_nextseek_run_query", fake_run_query, raising=True
            )
            monkeypatch.setattr(sys, "stdin", _FakeStdin("trigger failure\n"))

            # main() catches the exception, emits ns_runner_error, then re-raises OR sys.exit(1).
            # Implementation choice (Section 6 uses sys.exit(1)); test asserts a non-zero exit code.
            with pytest.raises(SystemExit) as excinfo:
                runner_ns.main(["--session", "test-sess"])
            assert excinfo.value.code != 0
        finally:
            os.close(events_fd)
            monkeypatch.setattr(runner_ns, "_EVENTS_FD", 1, raising=True)

    # Inspect captured stdout: exactly one ns_runner_error line carrying ONLY the type name.
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
