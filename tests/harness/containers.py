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
    """Confirm the dmac-assistant image exists; raise RuntimeError if not.

    Plan A T8 Amendment 4 (2026-04-29): the image must be built via
    `make image-build` (which runs `make sync-vendor-deps` first to
    populate `vendor/chat_nextseek/`). docker-py cannot drive a BuildKit
    build that depends on a host-side sync step, so this function does
    NOT auto-build — it surfaces a RuntimeError with a remediation
    message instead.
    """
    _allow_docker_unix_socket_only()
    client = docker.from_env()

    try:
        client.images.get(tag)
        return tag
    except ImageNotFound as exc:
        raise RuntimeError(
            f"dmac-assistant image not present; run `make image-build` first.\n"
            f"    make image-build\n"
            f"(docker-py auto-build is disabled per Plan A T8 Amendment 4 "
            f"because chat_nextseek requires a host-side `make sync-vendor-deps` "
            f"step before `docker buildx build`.)"
        ) from exc


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
