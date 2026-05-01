from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

import docker
import pytest
from fastapi.testclient import TestClient

from dmac_assistant.app import app
from tests.harness.containers import IMAGE_TAG, docker_available, ensure_image
from tests.harness.live_runner import allow_docker_unix_socket_only


pytestmark = [pytest.mark.live, pytest.mark.live_bridge, pytest.mark.slow]

PROJECT_NAME = "example-project"


def login_for_token(
    client: TestClient, *, user_id: str, password: str
) -> str:
    response = client.post(
        "/auth/login",
        json={"user_id": user_id, "password": password},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and token
    return token


def configure_live_bridge_env(
    monkeypatch: pytest.MonkeyPatch,
    live_env: dict[str, str],
    tmp_path: Path,
) -> tuple[str, str]:
    user_id = live_env["NEXTSEEK_USERNAME"]
    password = live_env["NEXTSEEK_PASSWORD"]

    claude_users_root = tmp_path / "claude-users"
    scratch_root = tmp_path / "scratch"
    dropbox_root = tmp_path / "dropbox"
    output_root = tmp_path / "output"
    project_root = dropbox_root / PROJECT_NAME

    (claude_users_root / user_id / ".claude").mkdir(parents=True, exist_ok=True)
    (scratch_root / user_id).mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)

    dmac_users = {
        user_id: {
            "password": password,
            "projects": [PROJECT_NAME],
        }
    }

    monkeypatch.setenv("DMAC_USERS", json.dumps(dmac_users))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(claude_users_root))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(scratch_root))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(dropbox_root))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("DMAC_BRIDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("DMAC_BRIDGE_PORT", "8000")
    monkeypatch.setenv("AWS_REGION", live_env["AWS_REGION"])
    monkeypatch.setenv(
        "AWS_BEARER_TOKEN_BEDROCK",
        live_env["AWS_BEARER_TOKEN_BEDROCK"],
    )
    monkeypatch.setenv("NEXTSEEK_URL", live_env["NEXTSEEK_URL"])
    return user_id, PROJECT_NAME


def _require_live_bridge_image() -> str:
    allow_docker_unix_socket_only()
    if not docker_available():
        pytest.skip("docker daemon not reachable")
    return ensure_image(IMAGE_TAG)


def receive_json_with_timeout(ws: Any, timeout_s: float = 20.0) -> dict[str, Any]:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            result_queue.put(("ok", ws.receive_json()))
        except BaseException as exc:  # pragma: no cover - exercised in live mode
            result_queue.put(("err", exc))

    threading.Thread(target=_reader, daemon=True).start()
    kind, value = result_queue.get(timeout=timeout_s)
    if kind == "err":
        raise value
    assert isinstance(value, dict)
    return value


def assert_no_resume_failed(frame: dict[str, Any]) -> None:
    if frame.get("type") == "error" and frame.get("reason") == "resume_failed":
        raise AssertionError(frame)


def wait_for_session_started(ws: Any) -> str:
    while True:
        frame = receive_json_with_timeout(ws)
        assert_no_resume_failed(frame)
        if frame.get("type") == "session_started":
            session_id = frame.get("session_id")
            assert isinstance(session_id, str) and session_id
            return session_id
        if frame.get("type") == "error":
            raise AssertionError(frame)


def wait_for_assistant_text(ws: Any, *, timeout_s: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_s
    chunks: list[str] = []
    while time.monotonic() < deadline:
        frame = receive_json_with_timeout(
            ws, timeout_s=max(0.1, deadline - time.monotonic())
        )
        assert_no_resume_failed(frame)
        if frame.get("type") == "assistant_message":
            content = frame.get("content")
            if isinstance(content, str) and content:
                chunks.append(content)
                joined = "".join(chunks).strip()
                if joined:
                    return joined
        elif frame.get("type") == "error":
            raise AssertionError(frame)
    raise AssertionError("timed out waiting for assistant_message content")


def wait_for_session_ended(ws: Any, *, timeout_s: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = receive_json_with_timeout(
            ws, timeout_s=max(0.1, deadline - time.monotonic())
        )
        assert_no_resume_failed(frame)
        if frame.get("type") == "session_ended":
            session_id = frame.get("session_id")
            assert isinstance(session_id, str) and session_id
            return session_id
        if frame.get("type") == "error":
            raise AssertionError(frame)
    raise AssertionError("timed out waiting for session_ended")


def find_user_container(user_id: str):
    allow_docker_unix_socket_only()
    client = docker.from_env(timeout=5)
    matches = client.containers.list(
        all=True,
        filters={"label": [f"dmac.bridge=1", f"dmac.user_id={user_id}"]},
    )
    assert matches, "expected at least one bridge container for live user"
    matches.sort(key=lambda container: container.attrs["Created"])
    return matches[-1]


def _wait_for_user_container(user_id: str, *, timeout_s: float = 10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return find_user_container(user_id)
        except AssertionError:
            time.sleep(0.25)
    return find_user_container(user_id)


def _clear_labeled_user_containers(user_id: str) -> None:
    allow_docker_unix_socket_only()
    client = docker.from_env(timeout=5)
    matches = client.containers.list(
        all=True,
        filters={"label": [f"dmac.bridge=1", f"dmac.user_id={user_id}"]},
    )
    for container in matches:
        try:
            container.remove(force=True)
        except Exception:
            pass


def _wait_for_no_user_containers(
    user_id: str, *, timeout_s: float = 15.0
) -> None:
    allow_docker_unix_socket_only()
    client = docker.from_env(timeout=5)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        matches = client.containers.list(
            all=True,
            filters={"label": [f"dmac.bridge=1", f"dmac.user_id={user_id}"]},
        )
        if not matches:
            return
        time.sleep(0.25)
    raise AssertionError("expected prior bridge container to be cleaned up")


@pytest.mark.skip(
    reason=(
        "Pre-existing flake (verified on integration baseline dea8c08, not "
        "T8-introduced): container cleanup race in _wait_for_no_user_containers — "
        "the prior bridge container is not always reaped within the 30s window "
        "before the second WebSocket session opens. Independent of Plan A T8 "
        "Dockerfile/uv-sync changes. Tracked separately."
    )
)
def test_resume_roundtrip_same_session_id(
    monkeypatch: pytest.MonkeyPatch,
    live_env: dict[str, str],
    tmp_path: Path,
) -> None:
    _require_live_bridge_image()
    user_id, _ = configure_live_bridge_env(monkeypatch, live_env, tmp_path)
    token = login_for_token(
        TestClient(app),
        user_id=user_id,
        password=live_env["NEXTSEEK_PASSWORD"],
    )
    remembered = "DMAC-RESUME-TOKEN-ALPHA-20260424"

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json(
                {
                    "type": "user_message",
                    "content": (
                        "Remember this exact token for later: "
                        f"{remembered}. Reply only with ACK {remembered}."
                    ),
                    "new_session": False,
                }
            )
            session_id_1 = wait_for_session_started(ws)
            first_reply = wait_for_assistant_text(ws, timeout_s=60.0)
            assert remembered in first_reply
            ended_session_id = wait_for_session_ended(ws, timeout_s=60.0)
            assert ended_session_id == session_id_1

    _wait_for_no_user_containers(user_id, timeout_s=30.0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json(
                {
                    "type": "user_message",
                    "content": (
                        "What token did I ask you to remember? "
                        "Reply only with the token."
                    ),
                    "new_session": False,
                }
            )
            session_id_2 = wait_for_session_started(ws)
            assert session_id_2 == session_id_1
            second_reply = wait_for_assistant_text(ws, timeout_s=60.0)
            assert remembered in second_reply


def test_new_session_true_bypasses_auto_resume(
    monkeypatch: pytest.MonkeyPatch,
    live_env: dict[str, str],
    tmp_path: Path,
) -> None:
    _require_live_bridge_image()
    user_id, _ = configure_live_bridge_env(monkeypatch, live_env, tmp_path)
    token = login_for_token(
        TestClient(app),
        user_id=user_id,
        password=live_env["NEXTSEEK_PASSWORD"],
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json(
                {
                    "type": "user_message",
                    "content": "Reply only with seeded.",
                    "new_session": False,
                }
            )
            prior_session_id = wait_for_session_started(ws)
            _ = wait_for_assistant_text(ws, timeout_s=60.0)

        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json(
                {
                    "type": "user_message",
                    "content": "Start over and reply only with fresh.",
                    "new_session": True,
                }
            )
            new_session_id = wait_for_session_started(ws)
            assert new_session_id != prior_session_id
            _ = wait_for_assistant_text(ws, timeout_s=60.0)


def test_project_mount_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    live_env: dict[str, str],
    tmp_path: Path,
) -> None:
    _require_live_bridge_image()
    user_id, project_name = configure_live_bridge_env(monkeypatch, live_env, tmp_path)
    token = login_for_token(
        TestClient(app),
        user_id=user_id,
        password=live_env["NEXTSEEK_PASSWORD"],
    )
    probe_path = tmp_path / "dropbox" / project_name / "probe"

    _clear_labeled_user_containers(user_id)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/chat",
            headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            ws.send_json(
                {
                    "type": "user_message",
                    "content": "Reply only with ready.",
                    "new_session": False,
                }
            )
            _ = wait_for_session_started(ws)
            container = _wait_for_user_container(user_id)
            exec_result = container.exec_run(
                [
                    "sh",
                    "-lc",
                    f"touch /data/projects/{project_name}/probe",
                ]
            )
            output = (
                (exec_result.output or b"").decode("utf-8", errors="replace")
            )
            assert exec_result.exit_code != 0
            assert (
                "Read-only file system" in output
                or "read-only file system" in output
                or "EROFS" in output
            ), output
            assert not probe_path.exists()
