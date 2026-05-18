"""NS-route in-image runner for the DMAC Assistant LLM router.

Invoked by the bridge as:
    python /opt/dmac/runner_ns.py [--session <id>]

Responsibilities (in execution order):
  1. fd-shuffle (module level): save fd 1 to _EVENTS_FD, then dup2(2, 1) so
     print()/sys.stdout.write() lands on docker exec's stderr channel. JSONL
     events are written exclusively to _EVENTS_FD via os.write().
  2. Test opt-out via DMAC_RUNNER_NS_NO_REMAP env var.
  3. Read user query from stdin (one line).
  4. Construct ChatConfig + SessionState from env + --session arg.
  5. Call chat_nextseek.orchestrator.run_query with a REDACTING send_event
     callback (defense in depth — see locked spec lines 481-498).
  6. On uncaught exception, emit {"event": "ns_runner_error", "payload":
     {"error_type": "<TypeName>"}} and exit non-zero.

See docs/superpowers/specs/2026-05-13-llm-router-design.md for the full design.
"""

# THIS BLOCK MUST BE THE FIRST EXECUTABLE STATEMENT IN THE MODULE, AT MODULE
# LEVEL (NOT INSIDE __main__). DO NOT INSERT ANY IMPORT THAT BINDS OR WRAPS
# sys.stdout / sys.stderr ABOVE THIS BLOCK. Plain `import os` is fine — it
# does not touch sys.stdout. The risk is any line that calls
# `sys.stdout = ...` or wraps the stream in a Tee-like object.
import os as _os


def _perform_event_channel_remap() -> int:
    """Save original fd 1 then redirect fd 1 -> fd 2. Returns the saved fd."""
    saved = _os.dup(1)
    _os.dup2(2, 1)
    return saved


if _os.environ.get("DMAC_RUNNER_NS_NO_REMAP"):
    _EVENTS_FD = 1  # test opt-out: leave fd table untouched
else:  # pragma: no cover  -- production-only branch; tests always set DMAC_RUNNER_NS_NO_REMAP=1
    _EVENTS_FD = _perform_event_channel_remap()
# After this point in production: fd 1 -> docker stderr pipe;
# _EVENTS_FD -> docker stdout pipe. In test mode (env var set):
# both _EVENTS_FD and fd 1 still point at the test's stdout; the
# test exercises _perform_event_channel_remap() under a controlled
# fd capture instead.

# All other imports go below — they may touch sys.stdout but only after the
# remap is complete.
import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402


# Failure-signal helpers for the redacting wrapper.

_FAILURE_STATUSES = frozenset({"error", "partial", "failure"})


def _has_failure_signal(payload: dict[str, Any]) -> bool:
    """True if ANY of the 5 union'd failure signals is present per spec line 491."""
    if payload.get("status") in _FAILURE_STATUSES:
        return True
    if payload.get("error_type"):
        return True
    if payload.get("error"):  # top-level legacy
        return True
    debug = payload.get("debug") or {}
    if debug.get("error"):
        return True
    if debug.get("fatal_error"):
        return True
    return False


def _redact_send_event(event_name: str, payload: dict[str, Any]) -> None:
    """Mutate payload in-place to redact credential-carrying fields.

    Per locked spec lines 481-498. Runs BEFORE each JSONL line is written.
    """
    if event_name == "query_error":
        if payload.get("error"):
            payload["error"] = "<redacted>"
        return

    if event_name != "query_complete":
        return

    # query_complete: union'd failure signals trigger reply redaction.
    debug = payload.get("debug") or {}
    if debug.get("error"):
        debug["error"] = "<redacted>"
    if debug.get("fatal_error"):
        debug["fatal_error"] = "<redacted>"

    if _has_failure_signal(payload) and payload.get("reply") is not None:
        payload["reply"] = "<redacted; see ns_query_complete_with_error frame>"


def _emit_jsonl(event_name: str, payload: dict[str, Any]) -> None:
    """Write one JSONL event line to the saved fd via os.write (NEVER print)."""
    line = json.dumps({"event": event_name, "payload": payload}, ensure_ascii=False)
    os.write(_EVENTS_FD, line.encode("utf-8") + b"\n")


def _make_redacting_send_event() -> Callable[[str, dict[str, Any]], None]:
    """Return a `send_event` callback that redacts then emits.

    Per locked spec line 486 (F-T1.3-1-3 round-1 hardener): on `query_error`,
    after the redacted main line is emitted, a SECOND JSONL line is emitted —
    `{"event": "ns_runner_error_type", "payload": {"agent": <agent>,
    "error_type": "RedactedByRunner"}}` — so the bridge can DEBUG-log the
    type-name signal that was redacted out of the main payload.
    """

    def send_event(event_name: str, payload: dict[str, Any]) -> None:
        _redact_send_event(event_name, payload)
        _emit_jsonl(event_name, payload)
        if event_name == "query_error":
            # Locked spec line 486: emit a separate post-event line carrying the
            # known-safe `agent` value + a sentinel `error_type`. The original
            # exception type-name is not recoverable here (the runner does not
            # have the exception object), so the literal "RedactedByRunner" is
            # the spec-mandated sentinel.
            _emit_jsonl(
                "ns_runner_error_type",
                {
                    "agent": payload.get("agent"),
                    "error_type": "RedactedByRunner",
                },
            )

    return send_event


def _run_chat_nextseek_run_query(  # pragma: no cover  -- DD-11 deferred chat_nextseek import; host-uncoverable, tests stub this helper
    session: Any,
    config: Any,
    user_text: str,
    *,
    send_event: Callable[[str, dict[str, Any]], None],
    credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Indirection layer for chat_nextseek.orchestrator.run_query.

    DD-11: chat_nextseek import is DEFERRED to inside this helper so the host
    venv (Python 3.12) can import container.runner_ns for unit tests without
    needing chat_nextseek (Python 3.14-only). Tests stub this function via
    monkeypatch.setattr(runner_ns, "_run_chat_nextseek_run_query", fake).

    The function body is excluded from host coverage measurement (`# pragma:
    no cover` at the def line) because under the test strategy this code path
    is replaced by the stub; the original body lines record zero hits per
    coverage.py mechanics (F-T1.3-4-1 round-4 hardener). The deferred body is
    exercised end-to-end in T4.2's 3.14-image integration tests.
    """
    from chat_nextseek.orchestrator import run_query

    return run_query(session, config, user_text, send_event=send_event, credentials=credentials)


def _build_chat_nextseek_session_and_config(session_id: str) -> tuple[Any, Any]:  # pragma: no cover  -- DD-11 deferred chat_nextseek import; host-uncoverable, tests stub this helper
    """Construct chat_nextseek SessionState + ChatConfig from env + session id.

    Per F-T1.3-1-1 / F-T1.3-1-2 round-1 hardener (verified against
    `vendor/chat_nextseek/src/chat_nextseek/config.py:14-15` and
    `vendor/chat_nextseek/src/chat_nextseek/session.py:56-66`):

    - `ChatConfig()` is the correct no-arg form (NOT `ChatConfig.from_env()` —
      that classmethod does NOT exist). `ChatConfig.__init__(config_map={})`
      reads env vars via `_get_env_config()` internally.
    - `SQLiteSessionState(db_path=..., session_id=...)` is the correct concrete
      class (NOT the abstract base `SessionState` which has no `__init__`).
      The `db_path` defaults to the locked-spec NS-only env value
      `CHAT_NEXTSEEK_SESSION_DB=/home/user/.claude/chat_nextseek/sessions.sqlite`
      per spec line 552.

    Also deferred so host tests don't need chat_nextseek importable.
    """
    from chat_nextseek.config import ChatConfig
    from chat_nextseek.session import SQLiteSessionState

    config = ChatConfig()
    db_path = os.environ.get(
        "CHAT_NEXTSEEK_SESSION_DB",
        "/home/user/.claude/chat_nextseek/sessions.sqlite",
    )
    session = SQLiteSessionState(db_path=db_path, session_id=session_id)
    return session, config


def main(argv: list[str] | None = None) -> int:
    """Entry point: read query from stdin, drive run_query, emit JSONL events."""
    parser = argparse.ArgumentParser(prog="runner_ns")
    parser.add_argument("--session", default=None, help="chat_nextseek session id")
    args = parser.parse_args(argv)

    # Read the single-line query from stdin (spec line 90).
    user_text = sys.stdin.readline().rstrip("\n")
    if not user_text:
        _emit_jsonl("ns_runner_error", {"error_type": "EmptyQuery"})
        sys.exit(2)

    redacting_send_event = _make_redacting_send_event()
    terminal_emitted = False

    def tracking_send_event(event_name: str, payload: dict[str, Any]) -> None:
        # Locked design spec L107: track whether chat_nextseek emitted a
        # terminal event so the runner can synthesize one after run_query
        # returns if it did not.
        nonlocal terminal_emitted
        if event_name in ("query_complete", "query_error"):
            terminal_emitted = True
        redacting_send_event(event_name, payload)

    try:
        session, config = _build_chat_nextseek_session_and_config(args.session or "default")
        _run_chat_nextseek_run_query(
            session, config, user_text, send_event=tracking_send_event, credentials=None
        )
        if not terminal_emitted:
            # Defense in depth against future chat_nextseek changes that might
            # silently drop the terminal-event contract. status=error +
            # error_type=RunnerSyntheticTerminal routes through the existing
            # _has_failure_signal path on the bridge side so the truncation
            # surfaces as ns_query_complete_with_error rather than masquerading
            # as success.
            _emit_jsonl(
                "query_complete",
                {
                    "reply": (
                        "<runner synthetic terminal: chat_nextseek run_query "
                        "returned without query_complete or query_error>"
                    ),
                    "status": "error",
                    "error_type": "RunnerSyntheticTerminal",
                },
            )
        return 0
    except BaseException as exc:  # noqa: BLE001 — R-03 demands BaseException catch
        # R-03: NEVER str(exc), NEVER repr(exc), NEVER exc.args.
        _emit_jsonl("ns_runner_error", {"error_type": type(exc).__name__})
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover  -- entry-point guard; tests call main() directly
    sys.exit(main())
