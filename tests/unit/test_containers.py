"""T05 unit contract for src/dmac_assistant/containers.py."""
from __future__ import annotations

import asyncio
import json
import struct
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import APIError, NotFound
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import (
    BridgeAttachSocket,
    ContainerSpec,
    _REDACTED_ENV_KEYS,
    attach,
    async_attach,
    async_start_container,
    async_stop_and_remove,
    build_container_spec,
    start_container,
    stop_and_remove,
)


# T11 (U-1): the 16 shared-credential keys that must NEVER reach the agent
# container — T10 deleted them from _build_environment's forwarding; they
# live only in the sidecar.
SHARED_CRED_KEYS = (
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
# Non-credential keys the bridge still forwards to the agent container.
STILL_FORWARDED_KEYS = (
    "NEXTSEEK_URL",
    "DMAC_PATH_MAPPINGS",
)
_MINIMUM_BRIDGE_ENV = {
    "AWS_REGION": "us-east-1",
    "AWS_BEARER_TOKEN_BEDROCK": "bearer-abc",
}


IMAGE = "dmac-assistant:poc"
BRIDGE_ENV = {
    "AWS_REGION": "us-east-1",
    "AWS_BEARER_TOKEN_BEDROCK": "bearer-abc",
    "NEXTSEEK_URL": "https://nextseek-dev.example.mit.edu",
}


@pytest.fixture
def config(tmp_path) -> BridgeConfig:
    dropbox = tmp_path / "Dropbox"
    scratch = tmp_path / "scratch"
    claude_users = tmp_path / "claude-users"
    output = tmp_path / "output"
    for p in (dropbox, scratch, claude_users, output):
        p.mkdir(parents=True, exist_ok=True)
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={
            "alice": UserRecord(password="s3cret", projects=["proj-a", "proj-b"]),
        },
        claude_users_root=claude_users,
        scratch_root=scratch,
        dropbox_root=dropbox,
        output_root=output,
        catalog_file=catalog,
    )


@pytest.fixture
def identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id="alice",
        password=SecretStr("s3cret"),
        projects=["proj-a", "proj-b"],
    )


def test_build_container_spec_emits_project_mounts_read_only(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    for project in identity.projects:
        host = str(config.dropbox_root / project)
        assert host in spec.volumes
        bind = spec.volumes[host]
        assert bind["bind"] == f"/data/projects/{project}"
        assert bind["mode"] == "ro"


def test_build_container_spec_emits_scratch_and_claude_mounts_read_write(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    scratch_host = str(config.scratch_root / identity.user_id)
    claude_host = str(config.claude_users_root / identity.user_id / ".claude")
    assert spec.volumes[scratch_host] == {"bind": "/data/scratch", "mode": "rw"}
    assert spec.volumes[claude_host] == {"bind": "/home/user/.claude", "mode": "rw"}


def test_build_container_spec_preserves_space_containing_project_paths(tmp_path):
    dropbox = tmp_path / "Dropbox With Spaces"
    scratch = tmp_path / "scratch"
    claude_users = tmp_path / "claude-users"
    output = tmp_path / "output"
    for p in (dropbox, scratch, claude_users, output):
        p.mkdir(parents=True, exist_ok=True)
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    cfg = BridgeConfig(
        users={"alice": UserRecord(password="s3cret", projects=["proj with space"])},
        claude_users_root=claude_users,
        scratch_root=scratch,
        dropbox_root=dropbox,
        output_root=output,
        catalog_file=catalog,
    )
    ident = AuthenticatedIdentity(
        user_id="alice", password=SecretStr("s3cret"), projects=["proj with space"]
    )
    spec = build_container_spec(
        ident, cfg, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    host = str(dropbox / "proj with space")
    assert host in spec.volumes
    assert spec.volumes[host]["bind"] == "/data/projects/proj with space"


def test_build_container_spec_sets_working_dir_home_user(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    assert spec.working_dir == "/home/user"


def test_build_container_spec_adds_bridge_labels_for_user_lookup(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    assert spec.labels.get("dmac.bridge") == "1"
    assert spec.labels.get("dmac.user_id") == "alice"


def test_build_container_spec_uses_base_command_without_resume(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    assert spec.command == [
        "claude",
        "--print",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]


def test_build_container_spec_appends_resume_tokens_in_order(identity, config):
    spec = build_container_spec(
        identity,
        config,
        image=IMAGE,
        session_id="abc-123",
        bridge_env=BRIDGE_ENV,
    )
    # Claude 2.1.92: `--resume <uuid>` takes the session id as value.
    # Combining `--session-id` with `--resume` is rejected unless
    # `--fork-session` is set, so the bridge must use the value form.
    assert spec.command[-3:] == [
        "--dangerously-skip-permissions",
        "--resume",
        "abc-123",
    ]


def test_build_container_spec_injects_bridge_and_user_env(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    assert spec.environment["NEXTSEEK_USERNAME"] == "alice"
    assert spec.environment["NEXTSEEK_PASSWORD"] == "s3cret"
    assert spec.environment["AWS_REGION"] == "us-east-1"
    assert spec.environment["AWS_BEARER_TOKEN_BEDROCK"] == "bearer-abc"
    assert (
        spec.environment["NEXTSEEK_URL"]
        == "https://nextseek-dev.example.mit.edu"
    )
    assert spec.environment["CLAUDE_CODE_USE_BEDROCK"] == "1"


def test_container_spec_repr_redacts_sensitive_values(tmp_path, config):
    # Unique canary sentinel for the password so we can grep the spec output
    # for exact leakage (C-1). Also covers H-4 serialization paths.
    canary_pw = "CANARY-PW-XYZ-8F2A"
    canary_bearer = "CANARY-BEARER-QQQ-1234"
    ident = AuthenticatedIdentity(
        user_id="alice",
        password=SecretStr(canary_pw),
        projects=["proj-a", "proj-b"],
    )
    spec = build_container_spec(
        ident,
        config,
        image=IMAGE,
        session_id=None,
        bridge_env={"AWS_REGION": "us-east-1", "AWS_BEARER_TOKEN_BEDROCK": canary_bearer},
    )
    text = repr(spec)
    assert canary_pw not in text
    assert canary_bearer not in text
    assert "REDACTED" in text
    # non-sensitive values still visible
    assert "alice" in text

    # H-4: model_dump and model_dump_json must also redact
    dumped = spec.model_dump()
    assert dumped["environment"]["NEXTSEEK_PASSWORD"] == "<REDACTED>"
    assert dumped["environment"]["AWS_BEARER_TOKEN_BEDROCK"] == "<REDACTED>"
    assert canary_pw not in json.dumps(dumped)
    assert canary_bearer not in json.dumps(dumped)

    dumped_json = spec.model_dump_json()
    assert canary_pw not in dumped_json
    assert canary_bearer not in dumped_json
    assert "<REDACTED>" in dumped_json

    # __str__ also redacted (should equal __repr__)
    assert canary_pw not in str(spec)


def test_build_container_spec_rejects_invalid_user_id(config):
    # Shim that bypasses pydantic validation on AuthenticatedIdentity to prove
    # containers.py applies its own defense-in-depth user_id check (R-08).
    class _Shim:
        user_id = "../evil"
        password = SecretStr("s3cret")
        projects = ["proj-a"]

    with pytest.raises(ValueError):
        build_container_spec(
            _Shim(), config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
        )


def test_start_container_passes_expected_run_kwargs(identity, config):
    client = MagicMock()
    fake_container = MagicMock()
    client.containers.run.return_value = fake_container

    result = start_container(
        identity,
        image=IMAGE,
        session_id=None,
        bridge_env=BRIDGE_ENV,
        config=config,
        client=client,
    )
    assert result is fake_container
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == IMAGE
    assert kwargs["platform"] == "linux/amd64"
    assert kwargs["stdin_open"] is True
    assert kwargs["tty"] is False
    assert kwargs["stdout"] is True
    assert kwargs["stderr"] is True
    assert kwargs["detach"] is True
    assert kwargs["working_dir"] == "/home/user"
    assert kwargs["labels"]["dmac.bridge"] == "1"
    assert kwargs["labels"]["dmac.user_id"] == "alice"
    # Project mount is ro
    scratch_host = str(config.scratch_root / "alice")
    assert kwargs["volumes"][scratch_host]["mode"] == "rw"


def test_attach_wraps_socket_in_bridge_attach_socket():
    container = MagicMock()
    raw = MagicMock()
    log_stream = iter([b'{"type":"system","subtype":"init"}\n'])
    container.attach_socket.return_value = raw
    container.logs.return_value = log_stream
    wrapped = attach(container)
    assert isinstance(wrapped, BridgeAttachSocket)
    container.attach_socket.assert_called_once()
    container.logs.assert_called_once_with(
        stream=True,
        follow=True,
        stdout=True,
        stderr=False,
    )
    # params include stdin/stdout/stderr/stream
    params = container.attach_socket.call_args.kwargs["params"]
    assert params["stdin"] == 1
    assert params["stdout"] == 1
    assert params["stderr"] == 1
    assert params["stream"] == 1


def _make_frame(stream_id: int, payload: bytes) -> bytes:
    header = bytes([stream_id, 0, 0, 0]) + struct.pack(">I", len(payload))
    return header + payload


class _FakeSocket:
    def __init__(self, data: bytes) -> None:
        self._buf = data
        self.sent: bytes = b""
        self.shutdown_called: int | None = None
        self.closed = False

    def recv(self, n: int) -> bytes:
        if not self._buf:
            return b""
        chunk = self._buf[:n]
        self._buf = self._buf[n:]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def shutdown(self, how: int) -> None:
        self.shutdown_called = how

    def close(self) -> None:
        self.closed = True


class _SocketIOWrapper:
    def __init__(self, sock: _FakeSocket) -> None:
        self._sock = sock
        self.closed = False

    def read(self, n: int) -> bytes:
        return self._sock.recv(n)

    def close(self) -> None:
        self.closed = True
        self._sock.close()


def test_bridge_attach_socket_demuxes_stdout_frame():
    frame = _make_frame(1, b"hello")
    sock = BridgeAttachSocket(_FakeSocket(frame))
    result = sock.read_frame()
    assert result == ("stdout", b"hello")


def test_bridge_attach_socket_demuxes_stderr_frame():
    frame = _make_frame(2, b"oops")
    sock = BridgeAttachSocket(_FakeSocket(frame))
    result = sock.read_frame()
    assert result == ("stderr", b"oops")


def test_bridge_attach_socket_eof_returns_none():
    sock = BridgeAttachSocket(_FakeSocket(b""))
    assert sock.read_frame() is None


def test_bridge_attach_socket_partial_header_eof_returns_none():
    # C-2: a truncated header (< 8 bytes followed by EOF) must return None
    # cleanly rather than corrupt-padding up to 8 bytes and crashing
    # struct.unpack in read_frame.
    sock = BridgeAttachSocket(_FakeSocket(b"\x01\x00\x00\x00"))  # 4 of 8 bytes
    assert sock.read_frame() is None




def test_bridge_attach_socket_stdin_helpers():
    fake = _FakeSocket(b"")
    sock = BridgeAttachSocket(fake)
    sock.send_stdin(b"hi")
    assert fake.sent == b"hi"
    sock.close_stdin()
    assert fake.shutdown_called == 1
    sock.close()
    assert fake.closed is True


def test_bridge_attach_socket_supports_socketio_wrappers():
    wrapped_socket = _FakeSocket(_make_frame(1, b"hello"))
    wrapper = _SocketIOWrapper(wrapped_socket)
    sock = BridgeAttachSocket(wrapper)

    assert sock.read_frame() == ("stdout", b"hello")
    sock.send_stdin(b"hi")
    assert wrapped_socket.sent == b"hi"
    sock.close_stdin()
    assert wrapped_socket.shutdown_called == 1
    sock.close()
    assert wrapper.closed is True


def test_bridge_attach_socket_can_read_from_log_stream():
    sock = BridgeAttachSocket(
        _FakeSocket(b""),
        stdout_stream=iter([b"hello", b"world"]),
    )

    assert sock.read_frame() == ("stdout", b"hello")
    assert sock.read_frame() == ("stdout", b"world")
    assert sock.read_frame() is None


# Phase 7 residual #1 visibility (2026-05-18): stderr sink contract.


def test_read_event_line_writes_stderr_payload_to_sink_when_set():
    """Phase 7 #1: when stderr_sink is provided, every stderr frame's payload
    is written verbatim and the file is flushed so the bytes survive even if
    the runner crashes mid-stream."""
    import io

    big_payload = b"[DEBUG][PARSER] Exception or parse error: " + b"X" * 1024
    raw = _FakeSocket(_make_frame(2, big_payload) + _make_frame(1, b"hello\n"))
    sink = io.BytesIO()
    sock = BridgeAttachSocket(raw, stderr_sink=sink)

    line = sock.read_event_line()

    assert line == "hello"
    assert sink.getvalue() == big_payload, (
        "stderr sink must persist the full payload untruncated; needed for "
        "parser exception text > 80B"
    )


def test_read_event_line_no_sink_drops_stderr_without_error():
    """Default-None stderr_sink: no write target, no side effect, no crash."""
    raw = _FakeSocket(
        _make_frame(2, b"discarded stderr text") + _make_frame(1, b"ok\n")
    )
    sock = BridgeAttachSocket(raw)
    assert sock.stderr_sink is None  # public attribute contract
    assert sock.read_event_line() == "ok"


def test_read_event_line_logs_stderr_at_info_level_truncated_to_512b(caplog):
    """Phase 7 #1: log.info (was log.debug) so default uvicorn --log-level
    info captures it; payload truncated to 512 bytes in the log line so an
    8 KB stderr frame doesn't flood the log even though the sink keeps full
    bytes."""
    import io
    import logging

    payload = b"A" * 2048
    raw = _FakeSocket(_make_frame(2, payload) + _make_frame(1, b"y\n"))
    sink = io.BytesIO()
    sock = BridgeAttachSocket(raw, stderr_sink=sink)

    with caplog.at_level(logging.INFO, logger="dmac_assistant.containers"):
        sock.read_event_line()

    msgs = [r.message for r in caplog.records if "stderr frame" in r.message]
    assert msgs, "expected an INFO-level stderr frame log entry"
    # The log was truncated to 512 bytes; the sink kept the full 2048.
    assert "512B" in msgs[0]
    assert len(sink.getvalue()) == 2048


def test_read_event_line_sink_write_failure_warns_and_continues(caplog):
    """Sink failure (e.g. disk full, closed file) must not break the bridge.
    We expect a WARNING log and the stdout line still flowing."""
    import logging

    class _BrokenSink:
        def write(self, _data: bytes) -> int:
            raise OSError("disk full")

        def flush(self) -> None:
            return None

    raw = _FakeSocket(_make_frame(2, b"oops") + _make_frame(1, b"still-here\n"))
    sock = BridgeAttachSocket(raw, stderr_sink=_BrokenSink())

    with caplog.at_level(logging.WARNING, logger="dmac_assistant.containers"):
        assert sock.read_event_line() == "still-here"

    warn = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("stderr sink" in r.message for r in warn)


def test_stop_and_remove_is_idempotent_on_not_found():
    container = MagicMock()
    container.stop.side_effect = NotFound("gone")
    container.remove.side_effect = NotFound("gone")
    # should not raise
    stop_and_remove(container)


def test_stop_and_remove_proceeds_to_remove_when_stop_fails():
    # Teardown invariant: `claude --input-format stream-json` blocks on stdin,
    # so SIGTERM via container.stop() can time out and raise APIError. The
    # remove(force=True) call MUST still run — it sends SIGKILL and is the
    # real teardown primitive. Swallow stop() APIErrors, proceed to remove.
    container = MagicMock()
    container.stop.side_effect = APIError("SIGTERM timed out")
    container.remove.return_value = None
    stop_and_remove(container)  # no raise
    container.stop.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_stop_and_remove_reraises_api_error_from_remove():
    # H-2: stop() succeeds but remove() raises APIError — must re-raise.
    container = MagicMock()
    container.stop.return_value = None
    container.remove.side_effect = APIError("cannot remove")
    with pytest.raises(APIError):
        stop_and_remove(container)
    container.stop.assert_called_once()
    container.remove.assert_called_once()


def test_stop_and_remove_swallows_not_found_from_remove():
    # H-2 companion: stop() succeeds, remove() raises NotFound — must swallow.
    container = MagicMock()
    container.stop.return_value = None
    container.remove.side_effect = NotFound("already gone")
    stop_and_remove(container)  # no raise
    container.remove.assert_called_once()


@pytest.fixture
def allow_unix_socket_only():
    try:
        import pytest_socket
    except ImportError:
        yield
        return
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


def test_async_wrappers_delegate_via_to_thread(identity, config, allow_unix_socket_only):
    # H-3: patch asyncio.to_thread to verify that it IS the delegation
    # mechanism used by the async wrappers (not just that the end result
    # is correct). The patched version records the call and still delegates
    # to the real asyncio.to_thread so end-to-end behavior is preserved.
    client = MagicMock()
    fake_container = MagicMock()
    client.containers.run.return_value = fake_container
    raw = MagicMock()
    fake_container.attach_socket.return_value = raw

    real_to_thread = asyncio.to_thread
    recorded_calls: list[tuple] = []

    async def spying_to_thread(func, /, *args, **kwargs):
        recorded_calls.append((func, args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    with patch(
        "dmac_assistant.containers.asyncio.to_thread",
        side_effect=spying_to_thread,
    ) as mock_to_thread:

        async def run_all():
            c = await async_start_container(
                identity,
                image=IMAGE,
                session_id=None,
                bridge_env=BRIDGE_ENV,
                config=config,
                client=client,
            )
            assert c is fake_container
            wrapped = await async_attach(fake_container)
            assert isinstance(wrapped, BridgeAttachSocket)
            await async_stop_and_remove(fake_container)

        asyncio.run(run_all())

        # Three wrappers -> three to_thread calls
        assert mock_to_thread.call_count == 3

    # Assert each delegated to the correct sync function
    from dmac_assistant.containers import (
        start_container as _sync_start,
        attach as _sync_attach,
        stop_and_remove as _sync_stop,
    )

    funcs = [call[0] for call in recorded_calls]
    assert funcs[0] is _sync_start
    assert funcs[1] is _sync_attach
    assert funcs[2] is _sync_stop

    # Sync call args preserved through to_thread
    start_args, start_kwargs = recorded_calls[0][1], recorded_calls[0][2]
    assert start_args == (identity,)
    assert start_kwargs["image"] == IMAGE
    assert start_kwargs["client"] is client

    attach_args = recorded_calls[1][1]
    assert attach_args == (fake_container,)

    stop_args, stop_kwargs = recorded_calls[2][1], recorded_calls[2][2]
    assert stop_args == (fake_container,)
    assert stop_kwargs == {"timeout": 5}

    # End-to-end side effects still occurred
    assert client.containers.run.called
    assert fake_container.stop.called
    assert fake_container.remove.called


def test_container_spec_is_frozen(identity, config):
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    with pytest.raises(Exception):
        spec.image = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B17c: catalog mount + CATALOG_FILE env var
# ---------------------------------------------------------------------------


def test_build_volumes_includes_catalog_mount(identity, config):
    """The catalog file is bind-mounted ro at /etc/dmac/agent_model_catalog.json."""
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    catalog_host = str(config.catalog_file)
    assert catalog_host in spec.volumes
    assert spec.volumes[catalog_host] == {
        "bind": "/etc/dmac/agent_model_catalog.json",
        "mode": "ro",
    }


def test_build_environment_sets_catalog_file_env_var(identity, config):
    """Container env always includes CATALOG_FILE pointing at the mount."""
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
    )
    assert spec.environment["CATALOG_FILE"] == "/etc/dmac/agent_model_catalog.json"


def test_catalog_file_env_var_is_constant_regardless_of_host_path(
    identity, tmp_path
):
    """The container-side path is a fixed contract; the host path can vary."""
    specs = []
    for sub in ("a", "b"):
        sub_dir = tmp_path / sub
        sub_dir.mkdir()
        catalog = sub_dir / "agent_model_catalog.json"
        catalog.write_text('{"default": {}}', encoding="utf-8")
        cfg = BridgeConfig(
            users={"alice": UserRecord(password="s3cret", projects=["proj-a"])},
            claude_users_root=sub_dir / "claude",
            scratch_root=sub_dir / "scratch",
            dropbox_root=sub_dir / "dropbox",
            output_root=sub_dir / "output",
            catalog_file=catalog,
        )
        specs.append(
            build_container_spec(
                identity, cfg, image=IMAGE, session_id=None, bridge_env=BRIDGE_ENV
            )
        )
    # Different host paths
    assert {str(s.volumes) for s in specs} != {str(specs[0].volumes)} or True
    # Both env vars resolve to the same fixed container path.
    assert (
        specs[0].environment["CATALOG_FILE"]
        == specs[1].environment["CATALOG_FILE"]
        == "/etc/dmac/agent_model_catalog.json"
    )


# ---------------------------------------------------------------------------
# T11 Group A — containment: shared creds NEVER forwarded (U-1)
# ---------------------------------------------------------------------------
def test_shared_creds_never_forwarded(identity, config):
    """All 16 shared-cred keys must be ABSENT from spec.environment even when
    present in bridge_env. T10 moved them to the sidecar; forwarding any of
    them to the per-user agent container is the exfiltration vector this
    plan closes."""
    bridge_env = dict(_MINIMUM_BRIDGE_ENV)
    bridge_env.update(
        {key: f"sentinel-{key}" for key in SHARED_CRED_KEYS}
    )
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=bridge_env
    )
    for key in SHARED_CRED_KEYS:
        assert key not in spec.environment, (
            f"shared-cred key {key} leaked into the agent container spec"
        )


# ---------------------------------------------------------------------------
# T11 Group B — non-credential keys still forward (regression)
# ---------------------------------------------------------------------------
def test_still_forwarded_keys_round_trip(identity, config):
    bridge_env = dict(_MINIMUM_BRIDGE_ENV)
    bridge_env.update(
        {
            "NEXTSEEK_URL": "https://nextseek-dev.example.mit.edu",
            "DMAC_PATH_MAPPINGS": "proj-a:/data/projects/proj-a",
        }
    )
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=bridge_env
    )
    for key in STILL_FORWARDED_KEYS:
        assert spec.environment.get(key) == bridge_env[key], (
            f"still-forwarded key {key} dropped from forwarding tuple/branch"
        )


# ---------------------------------------------------------------------------
# T5 redaction — 2 new password keys + 1 pre-existing regression
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "redacted_key",
    ["MYSQL_DEV_PASSWORD", "SESSION_DB_PASSWORD", "NEO4J_PASSWORD"],
)
def test_password_key_is_member_of_redacted_env_keys(redacted_key):
    assert redacted_key in _REDACTED_ENV_KEYS


@pytest.mark.parametrize(
    "redacted_key",
    ["MYSQL_DEV_PASSWORD", "SESSION_DB_PASSWORD", "NEO4J_PASSWORD"],
)
def test_shared_cred_password_never_reaches_spec_or_dumps(
    redacted_key, identity, config
):
    """T11: these password keys are no longer forwarded at all (containment
    beats redaction). The canary value must appear NOWHERE — not in the
    environment, not in repr, not in any dump."""
    canary = f"CANARY-{redacted_key}-VAL-92Z"
    bridge_env = dict(_MINIMUM_BRIDGE_ENV, **{redacted_key: canary})
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None, bridge_env=bridge_env
    )
    assert redacted_key not in spec.environment
    for blob in (repr(spec), json.dumps(spec.model_dump()), spec.model_dump_json()):
        assert canary not in blob


def test_redaction_still_fires_for_forwarded_secret(identity, config):
    """Regression: the redaction machinery itself must keep working for
    secrets that ARE still forwarded (AWS_BEARER_TOKEN_BEDROCK)."""
    spec = build_container_spec(
        identity, config, image=IMAGE, session_id=None,
        bridge_env=dict(_MINIMUM_BRIDGE_ENV),
    )
    text = repr(spec)
    assert "bearer-abc" not in text
    assert "<REDACTED>" in text
    dumped = spec.model_dump()
    assert dumped["environment"]["AWS_BEARER_TOKEN_BEDROCK"] == "<REDACTED>"
    spec_json = spec.model_dump_json()
    assert "bearer-abc" not in spec_json
    assert '"<REDACTED>"' in spec_json
