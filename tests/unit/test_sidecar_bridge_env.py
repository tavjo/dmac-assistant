"""T10 (U-1/U-8): after the sidecar lands, the agent container env holds NO
shared creds, and start_container attaches the agent to the sidecar network.

Does not collide with the migrated test_containers_env.py (T11)."""
from unittest.mock import MagicMock

import pytest
from docker.errors import NotFound
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import (
    _build_environment,
    _build_exec_environment,
    start_container,
)

SHARED = ("GCP_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE",
          "MYSQL_HOST_DEV", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DEV_PASSWORD",
          "SESSION_DB_TYPE", "SESSION_DB_HOST", "SESSION_DB_PORT", "SESSION_DB_USER",
          "SESSION_DB_PASSWORD", "SESSION_DB_NAME", "SESSION_DB_PATH")

IMAGE = "dmac-assistant:poc"


def _identity():
    return AuthenticatedIdentity(
        user_id="alice", password=SecretStr("pw"), projects=["proj-a"]
    )


def _config(tmp_path, *, sidecar_network):
    dropbox = tmp_path / "Dropbox"
    scratch = tmp_path / "scratch"
    claude_users = tmp_path / "claude-users"
    output = tmp_path / "output"
    for p in (dropbox, scratch, claude_users, output):
        p.mkdir(parents=True, exist_ok=True)
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return BridgeConfig(
        users={"alice": UserRecord(password="pw", projects=["proj-a"])},
        claude_users_root=claude_users,
        scratch_root=scratch,
        dropbox_root=dropbox,
        output_root=output,
        catalog_file=catalog,
        sidecar_network=sidecar_network,
    )


def test_shared_creds_not_in_agent_env():
    bridge_env = {k: "SENTINEL" for k in SHARED}
    bridge_env["NEXTSEEK_URL"] = "https://ns.example"
    bridge_env["DMAC_PATH_MAPPINGS"] = '{"scratch": {}}'
    env = _build_environment(_identity(), bridge_env)
    for k in SHARED:
        assert k not in env, f"{k} must not reach the agent container (U-1)"
    # the user's own login + NS url DO remain
    assert env["NEXTSEEK_USERNAME"] == "alice"
    assert env["NEXTSEEK_URL"] == "https://ns.example"
    # DMAC_PATH_MAPPINGS is NOT a credential and MUST still be forwarded (vet finding 7)
    assert env["DMAC_PATH_MAPPINGS"] == '{"scratch": {}}'


def test_exec_env_ns_route_drops_chat_nextseek_block():
    """U-8: session + outputs live in the sidecar; the thin runner_ns talks to
    the viewset, so the NS-route exec env carries no chat_nextseek wiring."""
    bridge_env = {"NEXTSEEK_BASE_URL": "http://ns.example"}
    env = _build_exec_environment(
        _identity(), bridge_env, route="ns", ns_session_id="sess-1"
    )
    for k in ("OUTPUTS_DIR", "CHAT_NEXTSEEK_SESSION_DB", "NEXTSEEK_MODE"):
        assert k not in env, f"{k} must not be set on the NS route after T10"
    # the per-exec basics survive
    assert env["API_USER"] == "alice"
    assert env["NEXTSEEK_BASE_URL"] == "http://ns.example"


# ------------------------------------------------- sidecar network attach (R-6)


def test_start_container_attaches_sidecar_network_when_it_exists(tmp_path):
    config = _config(tmp_path, sidecar_network="dmac-sidecar-net")
    client = MagicMock()
    client.networks.get.return_value = MagicMock()  # network exists
    client.containers.run.return_value = MagicMock()

    start_container(
        _identity(),
        image=IMAGE,
        session_id=None,
        bridge_env={},
        config=config,
        client=client,
    )
    client.networks.get.assert_called_once_with("dmac-sidecar-net")
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["network"] == "dmac-sidecar-net"


def test_start_container_fails_fast_when_sidecar_network_missing(tmp_path):
    """R-6: the bridge never manages compose — a missing sidecar network is a
    deployment error and must abort the spawn with a clear remedy."""
    config = _config(tmp_path, sidecar_network="dmac-sidecar-net")
    client = MagicMock()
    client.networks.get.side_effect = NotFound("no such network")

    with pytest.raises(RuntimeError) as excinfo:
        start_container(
            _identity(),
            image=IMAGE,
            session_id=None,
            bridge_env={},
            config=config,
            client=client,
        )
    msg = str(excinfo.value)
    assert "dmac-sidecar-net" in msg
    assert "make sidecar-up" in msg
    client.containers.run.assert_not_called()


def test_start_container_skips_network_when_not_configured(tmp_path):
    config = _config(tmp_path, sidecar_network=None)
    client = MagicMock()
    client.containers.run.return_value = MagicMock()

    start_container(
        _identity(),
        image=IMAGE,
        session_id=None,
        bridge_env={},
        config=config,
        client=client,
    )
    client.networks.get.assert_not_called()
    assert "network" not in client.containers.run.call_args.kwargs
