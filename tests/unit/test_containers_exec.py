"""T3.1 - exec_cc_turn / exec_ns_turn / kill_exec_pid contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from docker.errors import APIError
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import (
    BridgeAttachSocket,
    ContainerSpec,
    _REDACTED_ENV_KEYS,
    exec_cc_turn,
    exec_ns_turn,
    kill_exec_pid,
)


SECRET = "hunter2-not-a-real-password"
USER_ID = "alice"
SESSION_ID = "abc-123"
NS_SESSION_ID = "ns-deadbeef1234"
MODEL_ID = "us.anthropic.claude-sonnet-4-6"


class _RawSocketFake:
    """Minimal raw-socket-shaped fake matching docker exec_start(socket=True)."""

    def __init__(self, data: bytes = b"") -> None:
        self._buf = bytearray(data)
        self.sent = bytearray()
        self.shutdown_called: int | None = None
        self.closed = False

    def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def recv(self, n: int) -> bytes:
        return self.read(n)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def shutdown(self, how: int) -> None:
        self.shutdown_called = how

    def close(self) -> None:
        self.closed = True


class _FakeDockerAPI:
    def __init__(self, *, exec_pid: int | None = 4321) -> None:
        self.exec_create_calls: list[dict[str, Any]] = []
        self.exec_start_calls: list[dict[str, Any]] = []
        self.exec_inspect_calls: list[str] = []
        self._next_exec_id = 0
        self._sockets: list[_RawSocketFake] = []
        self._exec_pid = exec_pid

    def exec_create(self, container_id: str, **kwargs: Any) -> dict[str, str]:
        self._next_exec_id += 1
        exec_id = f"exec-{self._next_exec_id}"
        self.exec_create_calls.append(
            {"container_id": container_id, "exec_id": exec_id, **kwargs}
        )
        return {"Id": exec_id}

    def exec_start(self, exec_id: str, **kwargs: Any) -> _RawSocketFake:
        sock = _RawSocketFake()
        self._sockets.append(sock)
        self.exec_start_calls.append(
            {"exec_id": exec_id, "kwargs": kwargs, "socket": sock}
        )
        return sock

    def exec_inspect(self, exec_id: str) -> dict[str, Any]:
        self.exec_inspect_calls.append(exec_id)
        return {"Pid": self._exec_pid or 0, "Running": True, "ExitCode": None}


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeDockerAPI()


class _FakeContainer:
    def __init__(self, *, container_id: str = "ctr-deadbeef") -> None:
        self.id = container_id
        self.client = _FakeClient()

    def exec_run(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "container.exec_run MUST NOT be called; use low-level exec APIs"
        )


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id=USER_ID,
        password=SecretStr(SECRET),
        projects=["proj-a"],
    )


def _config(tmp_path: Path) -> BridgeConfig:
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={
            USER_ID: UserRecord(
                password=SecretStr(SECRET),
                projects=["proj-a"],
            ),
        },
        scratch_root=tmp_path / "scratch",
        output_root=tmp_path / "output",
        claude_users_root=tmp_path / "claude",
        dropbox_root=tmp_path / "dropbox",
        catalog_file=catalog,
    )


def _bridge_env_with_url(url: str = "https://nx.example.com") -> dict[str, str]:
    return {
        "AWS_REGION": "us-east-1",
        "AWS_BEARER_TOKEN_BEDROCK": "fake-bedrock-token-redact-me",
        "NEXTSEEK_URL": url,
        "NEXTSEEK_BASE_URL": url,
        "DMAC_PATH_MAPPINGS": '{"x":1}',
    }


def test_redacted_env_keys_contains_api_pass() -> None:
    assert "API_PASS" in _REDACTED_ENV_KEYS


@pytest.mark.parametrize(
    "key",
    [
        "NEXTSEEK_PASSWORD",
        "AWS_BEARER_TOKEN_BEDROCK",
        "NEO4J_PASSWORD",
        "GCP_API_KEY",
        "DMAC_PATH_MAPPINGS",
        "MYSQL_DEV_PASSWORD",
        "SESSION_DB_PASSWORD",
    ],
)
def test_redacted_env_keys_preserves_existing_entries(key: str) -> None:
    assert key in _REDACTED_ENV_KEYS


def test_container_spec_repr_redacts_api_pass() -> None:
    spec = ContainerSpec(
        image="img",
        command=["sh"],
        environment={"API_PASS": SECRET, "FOO": "bar"},
        volumes={},
        working_dir="/x",
        labels={},
    )
    rendered = repr(spec)
    assert SECRET not in rendered
    assert "<REDACTED>" in rendered
    assert "'FOO': 'bar'" in rendered


def test_container_spec_model_dump_redacts_api_pass() -> None:
    spec = ContainerSpec(
        image="img",
        command=["sh"],
        environment={"API_PASS": SECRET, "FOO": "bar"},
        volumes={},
        working_dir="/x",
        labels={},
    )
    dumped = spec.model_dump()
    assert dumped["environment"]["API_PASS"] == "<REDACTED>"
    assert dumped["environment"]["FOO"] == "bar"


def test_cc_argv_has_required_flags_and_model(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_cc_turn(
        container,
        query="hello",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    cmd = container.client.api.exec_create_calls[0]["cmd"]
    assert cmd[0] == "claude"
    assert "--print" in cmd
    assert "--input-format" in cmd
    assert cmd[cmd.index("--input-format") + 1] == "stream-json"
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd
    # OI-5: auto mode replaces --dangerously-skip-permissions on the CC turn.
    assert "--dangerously-skip-permissions" not in cmd
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"
    # OI-5: turn + dollar caps are always present.
    assert "--max-turns" in cmd
    assert "--max-budget-usd" in cmd
    # OI-5: inline trusted-infra allowlist for the auto-mode classifier; MUST
    # preserve the built-in defaults via the literal "$defaults".
    assert "--settings" in cmd
    assert "$defaults" in cmd[cmd.index("--settings") + 1]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == MODEL_ID
    assert "--resume" not in cmd


def test_cc_argv_includes_resume_when_session_id_given(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_cc_turn(
        container,
        query="hello",
        model_id=MODEL_ID,
        session_id=SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    cmd = container.client.api.exec_create_calls[0]["cmd"]
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == SESSION_ID
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == MODEL_ID


def test_cc_resume_with_model_switch_does_not_raise(tmp_path: Path) -> None:
    container = _FakeContainer()
    new_model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    sock = exec_cc_turn(
        container,
        query="hello",
        model_id=new_model,
        session_id=SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    assert isinstance(sock, BridgeAttachSocket)
    cmd = container.client.api.exec_create_calls[0]["cmd"]
    assert cmd[cmd.index("--model") + 1] == new_model
    assert cmd[cmd.index("--resume") + 1] == SESSION_ID


def test_cc_stdin_envelope_format(tmp_path: Path) -> None:
    container = _FakeContainer()
    query = "Find me mice treated with NDMA."
    exec_cc_turn(
        container,
        query=query,
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    raw_sock = container.client.api.exec_start_calls[0]["socket"]
    written = bytes(raw_sock.sent)
    assert written.endswith(b"\n")
    assert json.loads(written.decode("utf-8").rstrip("\n")) == {
        "type": "user",
        "message": {"role": "user", "content": query},
    }
    assert raw_sock.shutdown_called == 1


def test_ns_argv_includes_session_when_supplied(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_ns_turn(
        container,
        query="hello",
        session_id=NS_SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    cmd = container.client.api.exec_create_calls[0]["cmd"]
    assert cmd == ["python", "/opt/dmac/runner_ns.py", "--session", NS_SESSION_ID]


def test_ns_argv_omits_session_when_none(tmp_path: Path) -> None:
    # task-13R: the first NS turn of a WS connection has no captured viewset
    # session UUID yet (session_id=None). exec_ns_turn must omit --session
    # entirely so the assistant viewset creates a fresh session and returns its
    # UUID in the terminal query_complete event.
    container = _FakeContainer()
    exec_ns_turn(
        container,
        query="hello",
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    cmd = container.client.api.exec_create_calls[0]["cmd"]
    assert cmd == ["python", "/opt/dmac/runner_ns.py"]
    assert "--session" not in cmd


def test_ns_stdin_is_raw_query_with_newline(tmp_path: Path) -> None:
    container = _FakeContainer()
    query = "What samples are in the GBM study?"
    exec_ns_turn(
        container,
        query=query,
        session_id=NS_SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    raw_sock = container.client.api.exec_start_calls[0]["socket"]
    assert bytes(raw_sock.sent) == (query + "\n").encode("utf-8")
    assert raw_sock.shutdown_called == 1


@pytest.mark.parametrize("which", ["cc", "ns"])
def test_both_routes_env_has_shared_keys(which: str, tmp_path: Path) -> None:
    container = _FakeContainer()
    bridge_env = _bridge_env_with_url()
    common_kwargs = dict(
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=bridge_env,
    )
    if which == "cc":
        exec_cc_turn(container, model_id=MODEL_ID, session_id=None, **common_kwargs)
    else:
        exec_ns_turn(container, session_id=NS_SESSION_ID, **common_kwargs)
    env = container.client.api.exec_create_calls[0]["environment"]
    for key in (
        "API_USER",
        "API_PASS",
        "NEXTSEEK_USERNAME",
        "NEXTSEEK_PASSWORD",
        "NEXTSEEK_URL",
        "NEXTSEEK_BASE_URL",
        "DMAC_PATH_MAPPINGS",
        "CLAUDE_CODE_USE_BEDROCK",
        "AWS_REGION",
        "AWS_BEARER_TOKEN_BEDROCK",
    ):
        assert key in env, f"{which} route missing required env key: {key}"
    assert env["API_USER"] == USER_ID
    assert env["API_PASS"] == SECRET
    assert env["NEXTSEEK_USERNAME"] == USER_ID
    assert env["NEXTSEEK_PASSWORD"] == SECRET
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"


def test_nextseek_base_url_equals_bridge_url_value(tmp_path: Path) -> None:
    container = _FakeContainer()
    bridge_env = _bridge_env_with_url(url="https://nx.example.com")
    exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=bridge_env,
    )
    env = container.client.api.exec_create_calls[0]["environment"]
    assert env["NEXTSEEK_BASE_URL"] == bridge_env["NEXTSEEK_URL"]
    assert env["NEXTSEEK_BASE_URL"] == "https://nx.example.com"


@pytest.mark.parametrize("which", ["cc", "ns"])
def test_neo4j_database_never_forwarded(which: str, tmp_path: Path) -> None:
    """T11 (U-1): NEO4J_DATABASE is one of the 16 sidecar-held shared-cred
    keys — it must be ABSENT from the per-exec env even when set in
    bridge_env, on both routes."""
    container = _FakeContainer()
    bridge_env = {**_bridge_env_with_url(), "NEO4J_DATABASE": "neo4j-prod"}
    common_kwargs = dict(
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=bridge_env,
    )
    if which == "cc":
        exec_cc_turn(container, model_id=MODEL_ID, session_id=None, **common_kwargs)
    else:
        exec_ns_turn(container, session_id=NS_SESSION_ID, **common_kwargs)
    env = container.client.api.exec_create_calls[0]["environment"]
    assert "NEO4J_DATABASE" not in env


@pytest.mark.parametrize("which", ["cc", "ns"])
def test_neo4j_database_omitted_when_unset(which: str, tmp_path: Path) -> None:
    container = _FakeContainer()
    bridge_env = _bridge_env_with_url()
    assert "NEO4J_DATABASE" not in bridge_env
    common_kwargs = dict(
        query="hi",
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=bridge_env,
    )
    if which == "cc":
        exec_cc_turn(container, model_id=MODEL_ID, session_id=None, **common_kwargs)
    else:
        exec_ns_turn(container, session_id=NS_SESSION_ID, **common_kwargs)
    env = container.client.api.exec_create_calls[0]["environment"]
    assert "NEO4J_DATABASE" not in env


def test_ns_env_omits_chat_nextseek_keys(tmp_path: Path) -> None:
    """T11 (U-8): the NS route execs a thin client of the sidecar/viewset —
    OUTPUTS_DIR / CHAT_NEXTSEEK_SESSION_DB / NEXTSEEK_MODE were chat_nextseek
    process config and moved to the sidecar with it (T10 removed them from
    the NS exec env). They must be ABSENT."""
    container = _FakeContainer()
    exec_ns_turn(
        container,
        query="hi",
        session_id=NS_SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    env = container.client.api.exec_create_calls[0]["environment"]
    assert "OUTPUTS_DIR" not in env
    assert "CHAT_NEXTSEEK_SESSION_DB" not in env
    assert "NEXTSEEK_MODE" not in env


def test_cc_env_omits_outputs_dir(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    env = container.client.api.exec_create_calls[0]["environment"]
    assert "OUTPUTS_DIR" not in env
    assert "NEXTSEEK_MODE" not in env
    assert "CHAT_NEXTSEEK_SESSION_DB" not in env


def test_exec_create_called_with_correct_kwargs(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    call = container.client.api.exec_create_calls[0]
    assert call["stdin"] is True
    assert call["stdout"] is True
    assert call["stderr"] is True
    assert call["tty"] is False
    assert call["container_id"] == container.id


def test_exec_start_called_with_socket_true_and_no_demux(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_ns_turn(
        container,
        query="hi",
        session_id=NS_SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    call = container.client.api.exec_start_calls[0]
    assert call["kwargs"].get("socket") is True
    assert "demux" not in call["kwargs"]


def test_returns_bridge_attach_socket(tmp_path: Path) -> None:
    container = _FakeContainer()
    sock = exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    assert isinstance(sock, BridgeAttachSocket)


def test_kill_exec_pid_inspects_then_kills(tmp_path: Path) -> None:
    container = _FakeContainer()
    exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    api = container.client.api
    target_exec_id = api.exec_create_calls[0]["exec_id"]
    pre_exec_count = len(api.exec_create_calls)
    kill_exec_pid(container, target_exec_id)
    assert target_exec_id in api.exec_inspect_calls
    assert len(api.exec_create_calls) == pre_exec_count + 1
    assert api.exec_create_calls[-1]["cmd"] == ["kill", "-9", "4321"]


def test_kill_exec_pid_idempotent_when_no_pid() -> None:
    container = _FakeContainer()
    container.client.api._exec_pid = 0
    pre_exec_count = len(container.client.api.exec_create_calls)
    kill_exec_pid(container, "exec-nonexistent")
    assert len(container.client.api.exec_create_calls) == pre_exec_count
    assert "exec-nonexistent" in container.client.api.exec_inspect_calls


def test_kill_exec_pid_returns_on_exec_inspect_apierror(tmp_path: Path) -> None:
    del tmp_path
    container = _FakeContainer()

    def _raising_inspect(exec_id: str) -> dict[str, Any]:
        del exec_id
        raise APIError("docker daemon down")

    container.client.api.exec_inspect = _raising_inspect  # type: ignore[assignment]
    pre_exec_count = len(container.client.api.exec_create_calls)
    kill_exec_pid(container, "exec-broken")
    assert len(container.client.api.exec_create_calls) == pre_exec_count


def test_kill_exec_pid_returns_on_kill_start_apierror(tmp_path: Path) -> None:
    del tmp_path
    container = _FakeContainer()
    api = container.client.api

    def _raising_kill_create(container_id: str, **kwargs: Any) -> dict[str, str]:
        del container_id, kwargs
        raise APIError("kill exec_create failed")

    api.exec_create = _raising_kill_create  # type: ignore[assignment]
    pre_exec_count = len(api.exec_create_calls)
    kill_exec_pid(container, "exec-1")
    assert len(api.exec_create_calls) == pre_exec_count


def test_returns_socket_with_exec_id_attribute(tmp_path: Path) -> None:
    container = _FakeContainer()
    cc_sock = exec_cc_turn(
        container,
        query="hi",
        model_id=MODEL_ID,
        session_id=None,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    cc_exec_id = container.client.api.exec_create_calls[0]["exec_id"]
    assert getattr(cc_sock, "_exec_id", None) == cc_exec_id

    container2 = _FakeContainer()
    ns_sock = exec_ns_turn(
        container2,
        query="hi",
        session_id=NS_SESSION_ID,
        identity=_identity(),
        config=_config(tmp_path),
        bridge_env=_bridge_env_with_url(),
    )
    ns_exec_id = container2.client.api.exec_create_calls[0]["exec_id"]
    assert getattr(ns_sock, "_exec_id", None) == ns_exec_id
