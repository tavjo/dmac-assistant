"""R2 — tests for tools/e2e/router_dispatch.py.

Companion to plan llm-router-headless-batch-2026-05-18.md (TDD step R2).

Asserts:
  dispatch_cc:
    - forwards model_id verbatim to run_headless.run_one
    - tolerates model_id=None (router-fallback case)
    - returns a record dict from run_one
  dispatch_ns:
    - builds docker argv: `docker run --rm -i ... <image> python
      /opt/dmac/runner_ns.py --session <id>`
    - pipes query text on stdin
    - parses JSONL on stdout to derive final_answer, is_error,
      tool_use_summary, answer_provided, latency_seconds
    - distinguishes status=ok / status=error / ns_runner_error
    - leaves CC-only fields (cost_usd, num_turns, stop_reason) as None
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

# Module under test — created by G2.
from tools.e2e import router_dispatch  # noqa: E402  (module created in G2)


_SONNET_4_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"


# ----------------------------------------------------------------------- CC


def _baseline_cc_kwargs(tmp_path: pathlib.Path) -> dict:
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text("{}")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    return dict(
        query_text="hello",
        query_id="T-cc-1",
        image="dmac-assistant:poc",
        env={"NEXTSEEK_USERNAME": "demo", "NEXTSEEK_PASSWORD": "demo"},
        timeout=30,
        output_dir=tmp_path / "out",
        catalog_host_path=catalog,
        scratch_dir=scratch,
        claude_dir=claude_dir,
    )


def test_dispatch_cc_forwards_model_id_to_run_one(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run_one(**kwargs):
        captured.update(kwargs)
        return {"query_id": kwargs["query_id"], "is_error": False,
                "cost_usd": 0.01, "num_turns": 2, "stop_reason": "end_turn"}

    monkeypatch.setattr(router_dispatch.run_headless, "run_one", fake_run_one)

    record = router_dispatch.dispatch_cc(
        **_baseline_cc_kwargs(tmp_path),
        model_id=_SONNET_4_ID,
    )

    assert captured.get("model_id") == _SONNET_4_ID, (
        f"model_id must be forwarded verbatim; got {captured.get('model_id')!r}"
    )
    assert record["query_id"] == "T-cc-1"
    assert record["is_error"] is False


def test_dispatch_cc_passes_model_id_none_through(tmp_path, monkeypatch):
    """Router-fallback path: when model_class resolution failed and the
    caller passes model_id=None, dispatch_cc still forwards that None
    explicitly rather than dropping the kwarg."""
    captured: dict = {}

    def fake_run_one(**kwargs):
        captured.update(kwargs)
        return {"query_id": kwargs["query_id"], "is_error": False}

    monkeypatch.setattr(router_dispatch.run_headless, "run_one", fake_run_one)

    router_dispatch.dispatch_cc(
        **_baseline_cc_kwargs(tmp_path),
        model_id=None,
    )

    assert "model_id" in captured, (
        "dispatch_cc must forward model_id even when None"
    )
    assert captured["model_id"] is None


def test_dispatch_cc_returns_record_from_run_one(tmp_path, monkeypatch):
    expected = {
        "query_id": "T-cc-2",
        "is_error": False,
        "cost_usd": 0.12,
        "num_turns": 3,
        "stop_reason": "end_turn",
        "final_answer": "ok",
    }

    monkeypatch.setattr(
        router_dispatch.run_headless, "run_one", lambda **k: expected,
    )
    out = router_dispatch.dispatch_cc(
        **_baseline_cc_kwargs(tmp_path),
        model_id=_SONNET_4_ID,
    )
    assert out is expected


# ----------------------------------------------------------------------- NS


def _baseline_ns_kwargs(tmp_path: pathlib.Path, env_file: pathlib.Path) -> dict:
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text("{}")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    return dict(
        query_text="how many samples in proj-X?",
        query_id="T-ns-1",
        image="dmac-assistant:poc",
        env_file=env_file,
        timeout=30,
        output_dir=tmp_path / "out",
        catalog_host_path=catalog,
        scratch_dir=scratch,
        claude_dir=claude_dir,
        session_id="run-T-ns-1",
    )


def _write_env_file(tmp_path: pathlib.Path) -> pathlib.Path:
    env_file = tmp_path / ".env"
    env_file.write_text("NEXTSEEK_USERNAME=demo\nNEXTSEEK_PASSWORD=demo\n")
    return env_file


def _make_fake_subprocess_run(jsonl_events: list[dict]):
    """Return a fake subprocess.run that writes the given JSONL events to
    the file handle passed as stdout=, then exits 0."""
    captured_argv: list[list[str]] = []

    def _fake_run(cmd, *args, stdin=None, stdout=None, stderr=None,
                  timeout=None, **kwargs):
        captured_argv.append(list(cmd))
        if stdout is not None and hasattr(stdout, "write"):
            for ev in jsonl_events:
                stdout.write((json.dumps(ev) + "\n").encode("utf-8"))
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    return _fake_run, captured_argv


def test_dispatch_ns_builds_docker_argv(tmp_path, monkeypatch):
    env_file = _write_env_file(tmp_path)
    events = [{"event": "query_complete",
               "payload": {"status": "ok", "reply": "42 samples"}}]
    fake_run, captured = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--rm" in argv
    assert "-i" in argv
    assert "dmac-assistant:poc" in argv
    # python /opt/dmac/runner_ns.py --session <id> at the tail
    py_idx = argv.index("python")
    assert argv[py_idx + 1] == "/opt/dmac/runner_ns.py"
    assert "--session" in argv[py_idx + 2:]
    sess_idx = argv.index("--session")
    assert argv[sess_idx + 1] == "run-T-ns-1"
    # Env is forwarded as `-e KEY=VALUE` flags (NOT --env-file, because
    # docker's --env-file does not strip wrapping quotes from .env values).
    # Each -e should be followed by a KEY=VALUE pair.
    e_indices = [i for i, tok in enumerate(argv) if tok == "-e"]
    assert e_indices, "expected at least one -e flag in docker argv"
    seen_env_keys = {argv[i + 1].split("=", 1)[0] for i in e_indices}
    # Keys from our test env-file
    assert "NEXTSEEK_USERNAME" in seen_env_keys
    assert "NEXTSEEK_PASSWORD" in seen_env_keys
    # Added by dispatch_ns explicitly
    assert "CATALOG_FILE" in seen_env_keys
    # T11 review (M-1): the thin container/runner_ns.py no longer consumes
    # CHAT_NEXTSEEK_DB_ENV or NEXTSEEK_OUTPUTS_DIR (chat_nextseek left the
    # agent image for the sidecar) — the harness must mirror the post-T10
    # bridge and NOT inject them into the agent container env.
    assert "CHAT_NEXTSEEK_DB_ENV" not in seen_env_keys, (
        "dead injection: thin runner_ns.py does not read CHAT_NEXTSEEK_DB_ENV"
    )
    assert "NEXTSEEK_OUTPUTS_DIR" not in seen_env_keys, (
        "dead injection: chat_nextseek (consumer of NEXTSEEK_OUTPUTS_DIR) is "
        "no longer in the agent image"
    )
    # And --env-file specifically must NOT be present.
    assert "--env-file" not in argv, (
        "dispatch_ns must not use --env-file (it skips quote-stripping); "
        f"argv: {argv}"
    )


def test_dispatch_ns_strips_wrapping_quotes_from_env_file(tmp_path, monkeypatch):
    """Regression: a quoted value in .env (e.g. GCP_API_KEY=\"AIzaSy...\")
    must be parsed WITHOUT surrounding quotes (docker --env-file would
    forward them literally; we read+strip in Python instead).

    T11 review (M-1): what this test pins is .env PARSING, host-side. The
    stripped GCP_API_KEY value must NOT be forwarded into the agent
    container — shared creds live only in the sidecar post-T10. The
    quote-strip behavior itself is asserted on a forwarded key
    (NEXTSEEK_PASSWORD) plus directly on _read_dotenv_stripping_quotes.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        'NEXTSEEK_USERNAME=demo\n'
        'NEXTSEEK_PASSWORD="quoted-pw"\n'
        'GCP_API_KEY="AIzaSyExampleQuotedKey123456789012345"\n'
    )
    # Host-side parse: quotes stripped from every value, GCP_API_KEY included.
    parsed = router_dispatch._read_dotenv_stripping_quotes(env_file)
    assert parsed["GCP_API_KEY"] == "AIzaSyExampleQuotedKey123456789012345", (
        f"wrapping quotes must be stripped; got {parsed['GCP_API_KEY']!r}"
    )
    assert parsed["NEXTSEEK_PASSWORD"] == "quoted-pw"

    events = [{"event": "query_complete",
               "payload": {"status": "ok", "reply": "ok"}}]
    fake_run, captured = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    argv = captured[0]
    e_pairs = {
        argv[i + 1].split("=", 1)[0]: argv[i + 1].split("=", 1)[1]
        for i, tok in enumerate(argv) if tok == "-e"
    }
    # Forwarded key reaches the container quote-stripped...
    assert e_pairs.get("NEXTSEEK_PASSWORD") == "quoted-pw", (
        f"wrapping quotes must be stripped; got {e_pairs.get('NEXTSEEK_PASSWORD')!r}"
    )
    # ...but the shared-cred key must not reach the container at all.
    assert "GCP_API_KEY" not in e_pairs, (
        "GCP_API_KEY is a sidecar-held shared cred and must not be relayed "
        "into the agent container env"
    )


# T11 (U-1) parity with tests/unit/test_containers.py::SHARED_CRED_KEYS: the
# 16 shared-credential keys that must NEVER reach the agent container.
_SHARED_CRED_KEYS = (
    "GCP_API_KEY",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "MYSQL_HOST_DEV",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_DEV_PASSWORD",
    "SESSION_DB_TYPE",
    "SESSION_DB_HOST",
    "SESSION_DB_PORT",
    "SESSION_DB_USER",
    "SESSION_DB_PASSWORD",
    "SESSION_DB_NAME",
    "SESSION_DB_PATH",
)


def test_dispatch_ns_never_relays_shared_cred_keys_to_container(
    tmp_path, monkeypatch,
):
    """T11 review (M-1): the harness mimics the production bridge env, and
    post-T10 the bridge no longer forwards the 16 sidecar-held shared-cred
    keys. Even when .env carries all of them, none may appear in the
    container's -e flags — while legitimate keys still flow through."""
    env_file = tmp_path / ".env"
    lines = ["NEXTSEEK_USERNAME=demo\n", "NEXTSEEK_PASSWORD=demo\n"]
    lines += [f"{key}=sentinel-{key}\n" for key in _SHARED_CRED_KEYS]
    env_file.write_text("".join(lines))

    events = [{"event": "query_complete",
               "payload": {"status": "ok", "reply": "ok"}}]
    fake_run, captured = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    argv = captured[0]
    seen_env_keys = {
        argv[i + 1].split("=", 1)[0]
        for i, tok in enumerate(argv) if tok == "-e"
    }
    leaked = seen_env_keys & set(_SHARED_CRED_KEYS)
    assert not leaked, (
        f"shared-cred keys leaked into the agent container env: {sorted(leaked)}"
    )
    # Legitimate keys still relayed.
    assert "NEXTSEEK_USERNAME" in seen_env_keys
    assert "NEXTSEEK_PASSWORD" in seen_env_keys
    assert "CATALOG_FILE" in seen_env_keys


def test_dispatch_ns_success_record(tmp_path, monkeypatch):
    """chat_nextseek's success-path query_complete event has NO `status`
    field — only a `reply`. (Failure path adds status in the failure set
    or sets error_type / error.)"""
    env_file = _write_env_file(tmp_path)
    events = [
        {"event": "query_complete",
         "payload": {"reply": "42 samples in proj-X"}},  # no status key
    ]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    assert rec["answer_provided"] is True
    assert rec["final_answer"] == "42 samples in proj-X"
    assert rec["is_error"] is False
    assert rec.get("error") in (None, "")
    # CC-only fields must remain null on NS route
    assert rec["cost_usd"] is None
    assert rec["num_turns"] is None
    assert rec["stop_reason"] is None
    assert isinstance(rec.get("latency_seconds"), (int, float))


def test_dispatch_ns_success_record_with_status_ok(tmp_path, monkeypatch):
    """Backward compat: if a future runner emits status=ok explicitly,
    that must still be treated as success."""
    env_file = _write_env_file(tmp_path)
    events = [
        {"event": "query_complete",
         "payload": {"status": "ok", "reply": "42 samples"}},
    ]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    assert rec["answer_provided"] is True
    assert rec["final_answer"] == "42 samples"
    assert rec["is_error"] is False


def test_dispatch_ns_error_status_record(tmp_path, monkeypatch):
    env_file = _write_env_file(tmp_path)
    events = [
        {"event": "query_complete",
         "payload": {"status": "error", "reply": "could not resolve project",
                     "error_type": "ProjectNotFound"}},
    ]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    assert rec["is_error"] is True
    assert rec.get("error")  # populated with something non-empty
    assert rec["cost_usd"] is None


def test_dispatch_ns_runner_crash_record(tmp_path, monkeypatch):
    """ns_runner_error → is_error=True, final_answer=None.

    Runner emits this on any uncaught exception; query_complete is absent.
    """
    env_file = _write_env_file(tmp_path)
    events = [
        {"event": "ns_runner_error",
         "payload": {"error_type": "AttributeError"}},
    ]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))

    assert rec["is_error"] is True
    assert rec["final_answer"] is None
    assert rec["answer_provided"] is False
    assert rec["cost_usd"] is None


def test_dispatch_ns_unparseable_jsonl_does_not_crash(tmp_path, monkeypatch):
    """Garbled lines in the stdout JSONL are skipped, not fatal."""
    env_file = _write_env_file(tmp_path)

    def _fake_run(cmd, *args, stdin=None, stdout=None, stderr=None,
                  timeout=None, **kwargs):
        stdout.write(b"not json at all\n")
        stdout.write((json.dumps({
            "event": "query_complete",
            "payload": {"status": "ok", "reply": "recovered"},
        }) + "\n").encode("utf-8"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(router_dispatch.subprocess, "run", _fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))
    assert rec["is_error"] is False
    assert rec["final_answer"] == "recovered"


def test_dispatch_ns_tool_use_summary_empty_when_no_tool_call_events(
    tmp_path, monkeypatch,
):
    env_file = _write_env_file(tmp_path)
    events = [{"event": "query_complete",
               "payload": {"status": "ok", "reply": "done"}}]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))
    assert rec.get("tool_use_summary") == []


def test_dispatch_ns_timeout_marks_record_as_errored(tmp_path, monkeypatch):
    """subprocess.TimeoutExpired must produce a record with timed_out=True,
    is_error=True, and a non-None error string."""
    import subprocess as _sp
    env_file = _write_env_file(tmp_path)

    def _fake_run(cmd, *args, stdin=None, stdout=None, stderr=None,
                  timeout=None, input=None, **kwargs):
        raise _sp.TimeoutExpired(cmd=cmd, timeout=timeout or 30)

    monkeypatch.setattr(router_dispatch.subprocess, "run", _fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))
    assert rec["timed_out"] is True
    assert rec["is_error"] is True
    assert rec["error"]  # non-empty
    assert rec["final_answer"] is None


def test_dispatch_ns_no_terminal_event_is_error(tmp_path, monkeypatch):
    """Runner returned with no query_complete / query_error / ns_runner_error
    event (defense against future runner bugs) — must surface as is_error."""
    env_file = _write_env_file(tmp_path)
    # Emit only a harmless intermediate event, no terminal one.
    events = [{"event": "tool_call",
               "payload": {"tool": "Bash", "name": "ls"}}]
    fake_run, _ = _make_fake_subprocess_run(events)
    monkeypatch.setattr(router_dispatch.subprocess, "run", fake_run)

    rec = router_dispatch.dispatch_ns(**_baseline_ns_kwargs(tmp_path, env_file))
    assert rec["is_error"] is True
    assert rec["final_answer"] is None
    assert rec["error"]
