"""Docker-py helpers shared across smoke and later live-image tests."""
from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path
from typing import Iterator

import docker
from docker.errors import APIError, ImageNotFound
from docker.models.containers import Container


IMAGE_TAG = "dmac-assistant:poc"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _allow_docker_unix_socket_only() -> None:
    """Keep AF_INET blocked while allowing docker-py's Unix socket access.

    pytest-socket's default ``--disable-socket`` blocks Unix sockets in this
    environment too. Re-applying the guard with ``allow_unix_socket=True`` keeps
    outbound network closed while permitting dockerd access.
    """
    try:
        import pytest_socket
    except ImportError:
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)


def docker_available() -> bool:
    """Return True when both the docker binary and daemon are reachable."""
    _allow_docker_unix_socket_only()
    if shutil.which("docker") is None:
        return False

    try:
        client = docker.from_env(timeout=5)
        client.ping()
        return True
    except Exception:
        return False


def ensure_image(tag: str = IMAGE_TAG) -> str:
    """Return the local image tag, building it through docker-py if absent."""
    _allow_docker_unix_socket_only()
    client = docker.from_env()

    try:
        client.images.get(tag)
        return tag
    except ImageNotFound:
        pass

    client.images.build(
        path=str(REPO_ROOT),
        tag=tag,
        platform="linux/amd64",
        rm=True,
        pull=False,
    )
    client.images.get(tag)
    return tag


def seeded_settings_file(path: Path, payload: dict) -> None:
    """Write a settings file with the runtime-expected permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


@contextlib.contextmanager
def make_container(
    image: str,
    mounts: dict[str, tuple[str, str]],
    env: dict[str, str],
    command: list[str],
    entrypoint_override: list[str] | None = None,
    platform: str = "linux/amd64",
) -> Iterator[Container]:
    """Run a container in the foreground and always clean it up.

    ``mounts`` uses ``{host_path: (container_path, "ro"|"rw")}``.
    """
    _allow_docker_unix_socket_only()
    client = docker.from_env()
    volumes = {
        host_path: {"bind": container_path, "mode": mode}
        for host_path, (container_path, mode) in mounts.items()
    }
    kwargs = {
        "image": image,
        "command": command,
        "environment": env,
        "volumes": volumes,
        "detach": True,
        "platform": platform,
        "network_disabled": True,
        "stdout": True,
        "stderr": True,
    }
    if entrypoint_override is not None:
        kwargs["entrypoint"] = entrypoint_override

    container: Container = client.containers.run(**kwargs)
    try:
        yield container
    finally:
        try:
            container.remove(force=True)
        except APIError:
            pass
