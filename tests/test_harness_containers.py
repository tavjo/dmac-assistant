"""Unit tests for non-Docker branches of the shared container harness."""
from __future__ import annotations

import builtins
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError

from tests.harness.containers import (
    _allow_docker_unix_socket_only,
    docker_available,
    ensure_image,
    make_container,
)


def test_docker_available_false_when_docker_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing docker binary should short-circuit availability checks."""
    monkeypatch.setattr("tests.harness.containers.shutil.which", lambda name: None)
    assert docker_available() is False


def test_docker_available_false_when_ping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ping failure should be treated as daemon-unavailable, not fatal."""
    monkeypatch.setattr(
        "tests.harness.containers.shutil.which",
        lambda name: "/usr/local/bin/docker",
    )

    class _Boom:
        def ping(self) -> None:
            raise RuntimeError("daemon down")

    monkeypatch.setattr(
        "tests.harness.containers.docker.from_env",
        lambda *args, **kwargs: _Boom(),
    )
    assert docker_available() is False


def test_make_container_swallows_api_error_on_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup should swallow a container.remove race from docker-py."""
    fake_container = MagicMock()
    fake_container.remove.side_effect = APIError("removal race")

    fake_client = MagicMock()
    fake_client.containers.run.return_value = fake_container

    monkeypatch.setattr(
        "tests.harness.containers.docker.from_env",
        lambda *args, **kwargs: fake_client,
    )

    with make_container(
        image="dummy:test",
        mounts={},
        env={},
        command=["true"],
    ) as container:
        assert container is fake_container

    fake_container.remove.assert_called_once_with(force=True)


def test_allow_docker_unix_socket_only_ignores_missing_pytest_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper should quietly no-op when pytest-socket is unavailable."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pytest_socket":
            raise ImportError("missing for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    _allow_docker_unix_socket_only()


def test_ensure_image_returns_existing_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing local image should be returned without rebuilding."""
    fake_images = MagicMock()
    fake_images.get.return_value = object()

    fake_client = MagicMock()
    fake_client.images = fake_images

    monkeypatch.setattr(
        "tests.harness.containers._allow_docker_unix_socket_only",
        lambda: None,
    )
    monkeypatch.setattr(
        "tests.harness.containers.docker.from_env",
        lambda *args, **kwargs: fake_client,
    )

    assert ensure_image("dummy:test") == "dummy:test"
    fake_images.build.assert_not_called()
    fake_images.get.assert_called_once_with("dummy:test")


# Plan A T8 Amendment 4 (2026-04-30): the old `test_ensure_image_builds_when_missing`
# asserted auto-build behavior that has been removed. ensure_image() now raises
# RuntimeError when the image is absent, telling the operator to run
# `make image-build` (which itself runs `make sync-vendor-deps` first to
# populate `vendor/chat_nextseek/`). The replacement test asserting the new
# contract lives at tests/unit/test_harness_ensure_image_no_autobuild.py.
