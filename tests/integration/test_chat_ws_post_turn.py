"""Plan A · T6 (R5): drive chat_ws end-to-end and verify post-turn copy + DMAC_PATH_MAPPINGS."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr


class _FakeAttach:
    """Sync attach-socket double. `read_frame` MUST be sync — `_read_frame` in
    ws.py:175-178 wraps it in `asyncio.to_thread`. Returns (stream, payload)
    tuples (stream == "stdout") or None to signal EOF.

    Artifact creation is LAZY: the file MUST appear AFTER chat_ws has taken
    its pre_turn_files snapshot, not at construction time. Lazy creation
    fires when read_frame is about to return the final frame
    (len(self._frames) == 1).

    Plan A T12 (Amendment 10): artifact is now a flat file at
    <scratch_root>/<user_id>/marker.txt rather than a subdir + nested file.
    `artifact_file=None` (used by the eof_after_init=True branch) means
    no artifact is created on disk — preserves the prior `run_dir=None`
    sentinel semantics.
    """
    def __init__(self, frames, artifact_file=None):
        self._frames = list(frames)
        self._artifact_file = artifact_file
        self._artifact_created = False

    def read_frame(self):  # sync
        if not self._frames:
            return None
        if (self._artifact_file is not None
                and not self._artifact_created
                and len(self._frames) == 1):
            self._artifact_file.parent.mkdir(parents=True, exist_ok=True)
            self._artifact_file.write_text("x")
            self._artifact_created = True
        return self._frames.pop(0)

    def send_stdin(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        pass


def _build_fake_attach_emitting(artifact_file, *, eof_after_init: bool = False):
    """Return a _FakeAttach pre-loaded with a real Claude stream-json sequence.

    Always emits a `system/init` event first. Then either:
      * eof_after_init=False: emits a `result` event; _FakeAttach lazily creates
        the flat artifact_file on the read_frame call that returns that result.
      * eof_after_init=True:  no `result` event — read_frame returns None after init,
        which drives the synthetic-EOF branch in chat_ws (ws.py:360-410). The eof
        branch passes artifact_file=None to _FakeAttach so nothing is created on disk
        (preserves the eof_after_init=True semantics — no artifacts to copy).
    """
    frames = [
        ("stdout", b'{"type":"system","subtype":"init","session_id":"sid-1"}\n'),
    ]
    if not eof_after_init:
        frames.append(("stdout", b'{"type":"result"}\n'))
    return _FakeAttach(frames, artifact_file=None if eof_after_init else artifact_file)


@pytest.fixture
def _allow_unix_socket():
    """The repo-wide ``--disable-socket`` default in ``pyproject.toml`` blocks
    every socket including the AF_UNIX socketpair Starlette/anyio's TestClient
    needs to drive the WS loop. Re-enable just for the duration of this test.
    """
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


@pytest.mark.timeout(10)
@pytest.mark.parametrize("eof_after_init", [False, True], ids=["normal_turn_end", "synthetic_eof"])
def test_chat_ws_post_turn_copies_run(tmp_path, monkeypatch, eof_after_init, _allow_unix_socket):
    user_id = "alice"
    scratch = tmp_path / "scratch"
    output = tmp_path / "output"
    claude_users = tmp_path / "claude-users"
    dropbox = tmp_path / "dropbox"
    (scratch / user_id).mkdir(parents=True)
    output.mkdir()
    claude_users.mkdir()
    dropbox.mkdir()
    artifact_file = scratch / user_id / "marker.txt"

    captured_env = {}

    async def _capture_start(identity, *, image, session_id, bridge_env, config, **kwargs):
        assert identity.user_id == user_id
        captured_env.update(bridge_env)
        return object()  # opaque container handle

    fake_start = AsyncMock(side_effect=_capture_start)

    # MANDATORY R2 supplement (W4-C2): capture the fake_attach instance so the
    # post-WS-close `len(_frames) == 0` assertion can reach it.
    _last_fake_attach = _build_fake_attach_emitting(artifact_file, eof_after_init=eof_after_init)

    # IMPORTANT: patch the names AS BOUND IN ws.py, not in containers.
    # ws.py:37-41 does `from .containers import async_start_container, ...`,
    # which copies the names into ws.py's module namespace at import time.
    # Patching `dmac_assistant.containers.X` would NOT rebind the names that
    # chat_ws actually calls; the patch must hit `dmac_assistant.ws.X`.
    monkeypatch.setattr("dmac_assistant.ws.async_start_container", fake_start)
    monkeypatch.setattr(
        "dmac_assistant.ws.async_attach",
        AsyncMock(return_value=_last_fake_attach),
    )
    monkeypatch.setattr("dmac_assistant.ws.async_stop_and_remove", AsyncMock())

    # Point the bridge at the tmp_path roots and seed a valid config for load_config().
    monkeypatch.setenv("DMAC_DEV_MODE", "1")
    monkeypatch.setenv(
        "DMAC_USERS",
        json.dumps({user_id: {"password": "pw", "projects": ["proj-a"]}}),
    )
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(output))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(scratch))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(claude_users))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(dropbox))

    # Real subprotocol auth via dependency override. The test exercises the
    # `["dmac.bearer", "<token>"]` path (ws.py:73-110) — query strings like
    # `?user_id=...` are silently ignored by Starlette routing and must not
    # be relied on for identity.
    from dmac_assistant.app import app  # FastAPI factory, real route mounted
    from dmac_assistant.auth import AuthenticatedIdentity, get_token_store

    class _StubTokenStore:
        def verify(self, token: str) -> AuthenticatedIdentity:
            assert token == "test-token"
            return AuthenticatedIdentity(
                user_id=user_id,
                password=SecretStr("pw"),
                projects=["proj-a"],
            )

    app.dependency_overrides[get_token_store] = lambda: _StubTokenStore()
    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/chat", subprotocols=["dmac.bearer", "test-token"]
            ) as ws:
                ws.send_json({"type": "user_message", "content": "hi"})
                while True:
                    frame = ws.receive_json()
                    if frame.get("type") == "session_ended":
                        break
    finally:
        app.dependency_overrides.pop(get_token_store, None)

    # Post-turn copier ran on the new flat file (happy path only — eof variant
    # has no artifact, so the assertion below is gated on eof_after_init).
    if not eof_after_init:
        # Plan A T12 (Amendment 10): the directory-based subdir-publish path
        # is gone. Copier publishes flat files directly under <output>/<user_id>/.
        assert (output / user_id / "marker.txt").exists(), (
            "copier must publish flat marker.txt — directory-based "
            "subdir-publish path is gone (Plan A T12 Amendment 10)"
        )
    # DMAC_PATH_MAPPINGS reached the container in BOTH variants.
    mappings = json.loads(captured_env["DMAC_PATH_MAPPINGS"])
    assert mappings["output"]["container_root"] == "/data/output"
    assert mappings["output"]["host_root"] == str(output / user_id)
    assert mappings["scratch"]["container_root"] == "/data/scratch"
    assert mappings["scratch"]["host_root"] == str(scratch / user_id)

    # MANDATORY R2 supplement (W4-C2): unconditional behavioral sanity.
    # The locked body has no log signal that distinguishes the EOF branch
    # from the normal branch, so this assertion is the load-bearing R5-NEW-1
    # gate. After the WS closes, the fake's frame queue MUST be empty for
    # BOTH parametrize ids: normal_turn_end consumes [system/init, result]
    # via the WS loop, synthetic_eof consumes [system/init] then read_frame
    # returns None. Either way, _frames is empty.
    fake_attach_instance = _last_fake_attach
    assert len(fake_attach_instance._frames) == 0, (
        "fake attach has unconsumed frames — WS loop did not iterate "
        "to EOF. Synthetic-EOF branch may not have fired."
    )
