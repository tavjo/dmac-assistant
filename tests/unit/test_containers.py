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
    attach,
    async_attach,
    async_start_container,
    async_stop_and_remove,
    build_container_spec,
    start_container,
    stop_and_remove,
)


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
    for p in (dropbox, scratch, claude_users):
        p.mkdir(parents=True, exist_ok=True)
    return BridgeConfig(
        users={
            "alice": UserRecord(password="s3cret", projects=["proj-a", "proj-b"]),
        },
        claude_users_root=claude_users,
        scratch_root=scratch,
        dropbox_root=dropbox,
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
    for p in (dropbox, scratch, claude_users):
        p.mkdir(parents=True, exist_ok=True)
    cfg = BridgeConfig(
        users={"alice": UserRecord(password="s3cret", projects=["proj with space"])},
        claude_users_root=claude_users,
        scratch_root=scratch,
        dropbox_root=dropbox,
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
    assert spec.command[-4:] == [
        "--dangerously-skip-permissions",
        "--resume",
        "--session-id",
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


def test_stop_and_remove_is_idempotent_on_not_found():
    container = MagicMock()
    container.stop.side_effect = NotFound("gone")
    container.remove.side_effect = NotFound("gone")
    # should not raise
    stop_and_remove(container)


def test_stop_and_remove_reraises_unrelated_api_errors():
    container = MagicMock()
    container.stop.side_effect = APIError("daemon blew up")
    with pytest.raises(APIError):
        stop_and_remove(container)


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
