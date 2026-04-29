"""T05: Docker-py wrapper for the DMAC bridge's per-session container.

Owns four things (see task-05-containers spec):
  1. Mount assembly from AuthenticatedIdentity + BridgeConfig
  2. Command assembly for `claude --print --output-format stream-json ...`
  3. Container lifecycle (run / attach / stop / remove)
  4. Attach-socket normalization (Docker stdcopy demux -> stdout/stderr bytes)

DD-07: project mounts are `ro`; `/data/scratch` and `/home/user/.claude` are `rw`.
DD-13: every run uses working_dir="/home/user" so resume targets the correct cwd.
DD-14: T05 only appends `--resume <uuid>`; mismatch detection is T06.
R-02 split: T05 proves mount assembly; T07 does the live EROFS assertion.
R-03: ContainerSpec.__repr__ redacts sensitive env keys by name.
"""
from __future__ import annotations

import asyncio
import logging
import re
import struct
from typing import Any, Mapping

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from pydantic import BaseModel, ConfigDict

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig

log = logging.getLogger(__name__)

# Local defense-in-depth user_id validator (R-08): config.py exposes only a
# private _USER_ID_RE, so we mirror the anchored pattern here rather than
# importing a nonexistent public symbol.
_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_REDACTED_ENV_KEYS = frozenset({
    "NEXTSEEK_PASSWORD",
    "AWS_BEARER_TOKEN_BEDROCK",
    "NEO4J_PASSWORD",
    "GCP_API_KEY",
})

_BASE_COMMAND: tuple[str, ...] = (
    "claude",
    "--print",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
)

_CONTAINER_WORKING_DIR = "/home/user"
_CONTAINER_CLAUDE_HOME = "/home/user/.claude"
_CONTAINER_SCRATCH = "/data/scratch"
_CONTAINER_PROJECTS_PREFIX = "/data/projects"
_CONTAINER_OUTPUT = "/data/output"


class ContainerSpec(BaseModel):
    """Frozen description of a container to be launched."""

    model_config = ConfigDict(frozen=True)

    image: str
    command: list[str]
    environment: dict[str, str]
    volumes: dict[str, dict[str, str]]
    working_dir: str
    labels: dict[str, str]
    name: str | None = None

    def __repr__(self) -> str:  # pragma: no cover trivial
        safe_env = {
            k: ("<REDACTED>" if k in _REDACTED_ENV_KEYS else v)
            for k, v in self.environment.items()
        }
        return (
            f"ContainerSpec(image={self.image!r}, command={self.command!r}, "
            f"environment={safe_env!r}, volumes={self.volumes!r}, "
            f"working_dir={self.working_dir!r}, labels={self.labels!r}, "
            f"name={self.name!r})"
        )

    __str__ = __repr__

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Dump with sensitive env keys redacted.

        Pydantic's default model_dump bypasses __repr__, so without this
        override any operational logging that serializes the spec would leak
        NEXTSEEK_PASSWORD / AWS_BEARER_TOKEN_BEDROCK. Redaction applied here
        keeps the serialization contract aligned with __repr__.
        """
        data = super().model_dump(*args, **kwargs)
        env = data.get("environment")
        if isinstance(env, dict):
            data["environment"] = {
                k: ("<REDACTED>" if k in _REDACTED_ENV_KEYS else v)
                for k, v in env.items()
            }
        return data

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        """JSON dump with sensitive env keys redacted (see model_dump)."""
        import json

        return json.dumps(self.model_dump())


class BridgeAttachSocket:
    """Thin wrapper over docker-py's hijacked attach socket.

    Demuxes Docker's stdcopy 8-byte-header framing so callers read plain
    stdout/stderr payload bytes, and exposes stdin-side helpers the bridge
    needs for relaying WebSocket messages.
    """

    def __init__(
        self,
        raw_socket: Any,
        *,
        stdout_stream: Any | None = None,
    ) -> None:
        self._raw = raw_socket
        self._stdout_stream = stdout_stream

    # ------------------------------------------------------------------ read
    def read_frame(self) -> tuple[str, bytes] | None:
        """Read one Docker stdcopy frame.

        Returns ("stdout", payload), ("stderr", payload), or None on EOF.
        """
        if self._stdout_stream is not None:
            return self._read_log_chunk()
        header = self._recv_exact(8)
        if header is None:
            return None
        stream_id = header[0]
        size = struct.unpack(">I", header[4:8])[0]
        if size == 0:
            payload = b""
        else:
            payload = self._recv_exact(size) or b""
        stream_name = "stdout" if stream_id == 1 else "stderr"
        return stream_name, payload

    # ----------------------------------------------------------------- write
    def send_stdin(self, data: bytes) -> None:
        self._transport().sendall(data)

    def close_stdin(self) -> None:
        # 1 == SHUT_WR; avoid importing socket just for the constant so tests
        # can drop in a minimal fake.
        self._transport().shutdown(1)

    def close(self) -> None:
        if self._stdout_stream is not None and hasattr(self._stdout_stream, "close"):
            self._stdout_stream.close()
        self._raw.close()

    # ---------------------------------------------------------------- helper
    def _read_log_chunk(self) -> tuple[str, bytes] | None:
        try:
            payload = next(self._stdout_stream)
        except StopIteration:
            return None
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        return "stdout", payload

    def _recv_exact(self, size: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < size:
            chunk = self._read_chunk(size - len(buf))
            if not chunk:
                # Partial-frame EOF: return None so callers treat it as a clean
                # end-of-stream. Returning a short buffer would crash read_frame's
                # struct.unpack when the 8-byte header is truncated.
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _read_chunk(self, size: int) -> bytes:
        if hasattr(self._raw, "read"):
            return self._raw.read(size)
        return self._transport().recv(size)

    def _transport(self) -> Any:
        """Return the recv/send/shutdown-capable socket-like transport.

        docker-py often returns a ``SocketIO`` wrapper from ``attach_socket``.
        That wrapper exposes the real socket under ``._sock``; read/write
        operations that mutate the stream target the underlying transport, while
        reads go through the file-like wrapper when it exists so docker-py can
        manage any buffering correctly.
        """
        return getattr(self._raw, "_sock", self._raw)


# -------------------------------------------------------------------- helpers


def _validate_user_id(user_id: str) -> None:
    if not isinstance(user_id, str) or not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"invalid user_id: {user_id!r}")


def _build_volumes(
    identity: AuthenticatedIdentity, config: BridgeConfig
) -> dict[str, dict[str, str]]:
    volumes: dict[str, dict[str, str]] = {}
    for project in identity.projects:
        host = str(config.dropbox_root / project)
        volumes[host] = {
            "bind": f"{_CONTAINER_PROJECTS_PREFIX}/{project}",
            "mode": "ro",
        }
    volumes[str(config.scratch_root / identity.user_id)] = {
        "bind": _CONTAINER_SCRATCH,
        "mode": "rw",
    }
    volumes[str(config.claude_users_root / identity.user_id / ".claude")] = {
        "bind": _CONTAINER_CLAUDE_HOME,
        "mode": "rw",
    }
    volumes[str(config.output_root / identity.user_id)] = {
        "bind": _CONTAINER_OUTPUT,
        "mode": "ro",
    }
    return volumes


def _build_environment(
    identity: AuthenticatedIdentity, bridge_env: Mapping[str, str]
) -> dict[str, str]:
    env: dict[str, str] = {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "NEXTSEEK_USERNAME": identity.user_id,
        "NEXTSEEK_PASSWORD": identity.password.get_secret_value(),
    }
    if "AWS_REGION" in bridge_env:
        env["AWS_REGION"] = bridge_env["AWS_REGION"]
    if "AWS_BEARER_TOKEN_BEDROCK" in bridge_env:
        env["AWS_BEARER_TOKEN_BEDROCK"] = bridge_env["AWS_BEARER_TOKEN_BEDROCK"]
    if "NEXTSEEK_URL" in bridge_env:
        env["NEXTSEEK_URL"] = bridge_env["NEXTSEEK_URL"]
    for forwarded_key in ("GCP_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        if forwarded_key in bridge_env:
            env[forwarded_key] = bridge_env[forwarded_key]
    return env


def _build_command(session_id: str | None) -> list[str]:
    command = list(_BASE_COMMAND)
    if session_id:
        # Claude 2.1.92: `--resume <uuid>` takes the session id as its value.
        # `--session-id` is a separate flag (for pre-assigning a UUID to a
        # NEW session) and cannot be combined with --resume unless
        # --fork-session is also set; combining them emits
        # "--session-id can only be used with --continue or --resume if
        # --fork-session is also specified" and exits nonzero.
        command.extend(["--resume", session_id])
    return command


# --------------------------------------------------------------------- public


def build_container_spec(
    identity: AuthenticatedIdentity,
    config: BridgeConfig,
    *,
    image: str,
    session_id: str | None,
    bridge_env: Mapping[str, str],
) -> ContainerSpec:
    """Assemble the frozen ContainerSpec that `start_container` will launch."""
    _validate_user_id(identity.user_id)
    return ContainerSpec(
        image=image,
        command=_build_command(session_id),
        environment=_build_environment(identity, bridge_env),
        volumes=_build_volumes(identity, config),
        working_dir=_CONTAINER_WORKING_DIR,
        labels={
            "dmac.bridge": "1",
            "dmac.user_id": identity.user_id,
        },
    )


def start_container(
    identity: AuthenticatedIdentity,
    *,
    image: str,
    session_id: str | None,
    bridge_env: Mapping[str, str],
    config: BridgeConfig,
    client: Any | None = None,
) -> Container:
    """Build a spec and launch the container detached."""
    spec = build_container_spec(
        identity,
        config,
        image=image,
        session_id=session_id,
        bridge_env=bridge_env,
    )
    client = client or docker.from_env()
    run_kwargs: dict[str, Any] = {
        "image": spec.image,
        "command": spec.command,
        "environment": spec.environment,
        "volumes": spec.volumes,
        "working_dir": spec.working_dir,
        "labels": spec.labels,
        "platform": "linux/amd64",
        "detach": True,
        "stdin_open": True,
        "tty": False,
        "stdout": True,
        "stderr": True,
    }
    if spec.name is not None:
        run_kwargs["name"] = spec.name
    return client.containers.run(**run_kwargs)


def attach(container: Container) -> BridgeAttachSocket:
    """Open stdin via attach_socket and stdout via the working logs stream."""
    raw = container.attach_socket(
        params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
    )
    stdout_stream = container.logs(
        stream=True,
        follow=True,
        stdout=True,
        stderr=False,
    )
    return BridgeAttachSocket(raw, stdout_stream=stdout_stream)


def stop_and_remove(container: Container, *, timeout: int = 5) -> None:
    """Best-effort stop + remove.

    `remove(force=True)` MUST run even if `stop()` fails. `claude` in
    `--input-format stream-json` mode blocks on stdin, which means SIGTERM
    frequently times out and docker-py raises an APIError — if that short-
    circuits the remove call, the container is left alive and the next
    resume reconnect sees a stale sibling under the same label.
    `remove(force=True)` sends SIGKILL unconditionally and is the real
    teardown primitive.
    """
    try:
        container.stop(timeout=timeout)
    except NotFound:
        pass
    except APIError as exc:
        # Log only the exception type (R-03: APIError body may echo env).
        log.warning("container.stop failed: %s", type(exc).__name__)
    try:
        container.remove(force=True)
    except NotFound:
        pass
    except APIError as exc:
        log.error("container.remove failed: %s", type(exc).__name__)
        raise


# --------------------------------------------------------- async wrappers (T06)


async def async_start_container(
    identity: AuthenticatedIdentity,
    *,
    image: str,
    session_id: str | None,
    bridge_env: Mapping[str, str],
    config: BridgeConfig,
    client: Any | None = None,
) -> Container:
    return await asyncio.to_thread(
        start_container,
        identity,
        image=image,
        session_id=session_id,
        bridge_env=bridge_env,
        config=config,
        client=client,
    )


async def async_attach(container: Container) -> BridgeAttachSocket:
    return await asyncio.to_thread(attach, container)


async def async_stop_and_remove(container: Container, *, timeout: int = 5) -> None:
    await asyncio.to_thread(stop_and_remove, container, timeout=timeout)
