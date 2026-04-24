"""T02 config tests: DMAC_USERS shape, redaction, user_id rules, path-root loading."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


GOOD_USERS = {
    "alice": {"password": "s3cret-alice", "projects": ["proj-a"]},
    "bob-1": {"password": "s3cret-bob", "projects": ["proj-a", "proj-b"]},
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip all bridge variables so each test sets only what it needs."""
    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
        "DMAC_BRIDGE_HOST",
        "DMAC_BRIDGE_PORT",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _set_good_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    users: dict[str, object] | None = None,
    claude_users_root: str = "./var/claude-users",
    scratch_root: str = "./var/scratch",
    dropbox_root: str = "/tmp/dropbox-fake",
    bridge_host: str = "127.0.0.1",
    bridge_port: str = "8000",
) -> None:
    monkeypatch.setenv("DMAC_USERS", json.dumps(users if users is not None else GOOD_USERS))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", claude_users_root)
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", scratch_root)
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", dropbox_root)
    monkeypatch.setenv("DMAC_BRIDGE_HOST", bridge_host)
    monkeypatch.setenv("DMAC_BRIDGE_PORT", bridge_port)


def test_load_config_happy_path(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env)

    from dmac_assistant.config import load_config

    config = load_config()

    assert set(config.users) == {"alice", "bob-1"}
    assert config.users["alice"].projects == ["proj-a"]
    assert config.bridge_host == "127.0.0.1"
    assert config.bridge_port == 8000
    assert config.claude_users_root == Path("./var/claude-users")
    assert config.scratch_root == Path("./var/scratch")
    assert config.dropbox_root == Path("/tmp/dropbox-fake")


def test_bridge_config_is_frozen(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env)

    from dmac_assistant.config import load_config

    config = load_config()
    with pytest.raises((TypeError, ValueError, AttributeError, ExceptionGroup)):
        config.bridge_port = 9999  # type: ignore[misc]


def test_load_config_rejects_missing_dmac_users(clean_env: pytest.MonkeyPatch) -> None:
    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="DMAC_USERS"):
        load_config()


def test_bridge_config_rejects_empty_users_directly() -> None:
    from pydantic import ValidationError

    from dmac_assistant.config import BridgeConfig

    with pytest.raises(ValidationError, match="at least one user"):
        BridgeConfig(
            users={},
            claude_users_root="./var/claude-users",
            scratch_root="./var/scratch",
            dropbox_root="./dropbox",
        )


def test_load_config_rejects_non_json_dmac_users(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DMAC_USERS", "not-json-at-all")
    clean_env.setenv("DMAC_CLAUDE_USERS_ROOT", "./x")
    clean_env.setenv("DMAC_SCRATCH_ROOT", "./y")
    clean_env.setenv("DMAC_DROPBOX_ROOT", "./z")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config()


def test_load_config_rejects_non_object_dmac_users(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DMAC_USERS", "[]")
    clean_env.setenv("DMAC_CLAUDE_USERS_ROOT", "./x")
    clean_env.setenv("DMAC_SCRATCH_ROOT", "./y")
    clean_env.setenv("DMAC_DROPBOX_ROOT", "./z")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="decode to an object"):
        load_config()


def test_load_config_rejects_empty_user_map(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, users={})

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="at least one user"):
        load_config()


@pytest.mark.parametrize(
    "bad_user_id",
    [
        "../etc",
        "user/subdir",
        "user with spaces",
        "",
        "a" * 65,
        "user.name",
        "user@host",
        "user\u0000null",
    ],
)
def test_load_config_rejects_bad_user_ids(
    clean_env: pytest.MonkeyPatch,
    bad_user_id: str,
) -> None:
    _set_good_env(clean_env, users={bad_user_id: {"password": "x", "projects": ["p"]}})

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert "user_id" in str(exc_info.value).lower()


def test_load_config_accepts_max_length_user_id(clean_env: pytest.MonkeyPatch) -> None:
    user_id = "a" * 64
    _set_good_env(clean_env, users={user_id: {"password": "x", "projects": ["p"]}})

    from dmac_assistant.config import load_config

    config = load_config()
    assert user_id in config.users


def test_user_record_password_is_redacted_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env)

    from dmac_assistant.config import load_config

    config = load_config()
    user = config.users["alice"]

    assert "s3cret-alice" not in repr(user)
    assert "s3cret-alice" not in str(user)
    assert "s3cret-alice" not in repr(config)
    assert "s3cret-alice" not in str(config)


def test_user_record_password_is_retrievable_via_get_secret_value(
    clean_env: pytest.MonkeyPatch,
) -> None:
    _set_good_env(clean_env)

    from dmac_assistant.config import load_config

    config = load_config()
    assert config.users["alice"].password.get_secret_value() == "s3cret-alice"


def test_config_error_message_does_not_leak_password(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv(
        "DMAC_USERS",
        '{"alice": {"password": "LEAK-ME-IF-YOU-CAN", "projects": ["p"],}}',
    )
    clean_env.setenv("DMAC_CLAUDE_USERS_ROOT", "./x")
    clean_env.setenv("DMAC_SCRATCH_ROOT", "./y")
    clean_env.setenv("DMAC_DROPBOX_ROOT", "./z")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert "LEAK-ME-IF-YOU-CAN" not in str(exc_info.value)


def test_dev_mode_supplies_default_roots(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DMAC_DEV_MODE", "1")
    clean_env.setenv("DMAC_USERS", json.dumps(GOOD_USERS))

    from dmac_assistant.config import load_config

    config = load_config()
    assert config.claude_users_root.name == "claude-users"
    assert config.scratch_root.name == "scratch"
    assert config.dropbox_root.name == "DMAC_Data"


def test_prod_mode_requires_all_path_roots(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DMAC_USERS", json.dumps(GOOD_USERS))

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="DMAC_CLAUDE_USERS_ROOT"):
        load_config()


def test_load_config_rejects_empty_projects(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, users={"alice": {"password": "x", "projects": []}})

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="invalid user records"):
        load_config()


def test_load_config_rejects_blank_project_names(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, users={"alice": {"password": "x", "projects": [" "]}})

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="invalid user records"):
        load_config()


def test_load_config_rejects_blank_bridge_host(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, bridge_host="   ")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="Bridge configuration is invalid"):
        load_config()


def test_load_config_rejects_out_of_range_bridge_port(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, bridge_port="70000")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="Bridge configuration is invalid"):
        load_config()


def test_load_config_rejects_non_integer_bridge_port(clean_env: pytest.MonkeyPatch) -> None:
    _set_good_env(clean_env, bridge_port="abc")

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="Bridge configuration is invalid"):
        load_config()
