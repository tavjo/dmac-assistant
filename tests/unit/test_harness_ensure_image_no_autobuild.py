"""Plan A T8 Amendment 4: ensure_image() must NOT auto-build.

When the image is absent, ensure_image must raise RuntimeError pointing
operators at `make image-build` (which depends on `make sync-vendor-deps`
to populate `vendor/chat_nextseek/` on the host first).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from docker.errors import ImageNotFound

from tests.harness.containers import ensure_image


def test_ensure_image_raises_when_missing() -> None:
    """ensure_image must fail loudly when the image is absent — never auto-build."""
    fake_client = MagicMock()
    fake_client.images.get.side_effect = ImageNotFound("no such image")

    with patch("tests.harness.containers.docker.from_env", return_value=fake_client):
        with pytest.raises(RuntimeError) as excinfo:
            ensure_image()

    msg = str(excinfo.value)
    assert "make image-build" in msg, f"error must reference `make image-build`: {msg!r}"
    # Auto-build (client.images.build) must never have been called.
    fake_client.images.build.assert_not_called()


def test_ensure_image_returns_tag_when_present() -> None:
    """When the image exists, ensure_image returns its tag without raising."""
    fake_client = MagicMock()
    fake_client.images.get.return_value = MagicMock()

    with patch("tests.harness.containers.docker.from_env", return_value=fake_client):
        tag = ensure_image("dmac-assistant:poc")

    assert tag == "dmac-assistant:poc"
    fake_client.images.build.assert_not_called()
