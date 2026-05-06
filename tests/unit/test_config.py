"""T02 config tests: DMAC_USERS shape, redaction, user_id rules, path-root loading."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_catalog(tmp_path: Path) -> Path:
    """Write a minimal-but-valid JSON catalog under tmp_path and return it."""
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    return catalog


GOOD_USERS = {
    "alice": {"password": "s3cret-alice", "projects": ["proj-a"]},
    "bob-1": {"password": "s3cret-bob", "projects": ["proj-a", "proj-b"]},
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Strip all bridge variables so each test sets only what it needs.

    B17c: also pre-populates DMAC_CATALOG_FILE_HOST_PATH so existing tests
    that don't care about catalog wiring still resolve a valid catalog file.
    Tests that DO care (the catalog_file tests) call monkeypatch.setenv /
    monkeypatch.delenv themselves to override.
    """
    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
        "DMAC_OUTPUT_ROOT",
        "DMAC_CATALOG_FILE_HOST_PATH",
        "DMAC_BRIDGE_HOST",
        "DMAC_BRIDGE_PORT",
    ):
        monkeypatch.delenv(var, raising=False)
    # Avoid loading the developer's real repo `.env` into tests (would defeat delenv).
    import dmac_assistant.config as config_mod

    isolated = tmp_path / "no_dotenv_here"
    isolated.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", isolated, raising=False)

    # B17c: provide a default valid catalog so the new required-field load
    # path resolves. Tests that exercise catalog-file behavior override this.
    default_catalog = tmp_path / "agent_model_catalog_default.json"
    default_catalog.write_text('{"default": {}}', encoding="utf-8")
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(default_catalog))
    return monkeypatch


def _set_good_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    users: dict[str, object] | None = None,
    claude_users_root: str = "./var/claude-users",
    scratch_root: str = "./var/scratch",
    dropbox_root: str = "/tmp/dropbox-fake",
    output_root: str = "/tmp/output-fake",
    catalog_file: str | None = None,
    bridge_host: str = "127.0.0.1",
    bridge_port: str = "8000",
) -> None:
    monkeypatch.setenv("DMAC_USERS", json.dumps(users if users is not None else GOOD_USERS))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", claude_users_root)
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", scratch_root)
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", dropbox_root)
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", output_root)
    if catalog_file is not None:
        monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", catalog_file)
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
            output_root="./output",
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


def test_load_config_reads_env_from_repo_root_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.env` at anchored repo root loads DMAC_USERS even when cwd is elsewhere."""
    dotenv_home = tmp_path / "repo"
    dotenv_home.mkdir()
    users = {"from-dotenv": {"password": "pw", "projects": ["p1"]}}
    env_body = (
        f"DMAC_DEV_MODE=1\n"
        f"DMAC_USERS={json.dumps(users)}\n"
        f"DMAC_CLAUDE_USERS_ROOT=./cu\n"
        f"DMAC_SCRATCH_ROOT=./sc\n"
        f"DMAC_DROPBOX_ROOT=./db\n"
    )
    (dotenv_home / ".env").write_text(env_body, encoding="utf-8")

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

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    import dmac_assistant.config as config_mod

    monkeypatch.setattr(config_mod, "_REPO_ROOT", dotenv_home, raising=False)

    from dmac_assistant.config import load_config

    cfg = load_config()
    assert "from-dotenv" in cfg.users


def test_real_env_wins_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shell env beats .env when values disagree (override=False)."""
    dotenv_home = tmp_path / "repo"
    dotenv_home.mkdir()
    file_users = {"file-user": {"password": "pw", "projects": ["p1"]}}
    (dotenv_home / ".env").write_text(
        f"DMAC_DEV_MODE=1\nDMAC_USERS={json.dumps(file_users)}\n"
        "DMAC_CLAUDE_USERS_ROOT=./cu\nDMAC_SCRATCH_ROOT=./sc\nDMAC_DROPBOX_ROOT=./db\n",
        encoding="utf-8",
    )

    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)

    env_users = {"env-user": {"password": "pw2", "projects": ["p2"]}}
    monkeypatch.setenv("DMAC_DEV_MODE", "1")
    monkeypatch.setenv("DMAC_USERS", json.dumps(env_users))

    import dmac_assistant.config as config_mod

    monkeypatch.setattr(config_mod, "_REPO_ROOT", dotenv_home, raising=False)

    from dmac_assistant.config import load_config

    cfg = load_config()
    assert set(cfg.users) == {"env-user"}


def test_no_dotenv_file_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing .env at anchored path is fine when os.environ supplies config."""
    empty_root = tmp_path / "no-env-file"
    empty_root.mkdir()

    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("DMAC_DEV_MODE", "1")
    monkeypatch.setenv("DMAC_USERS", json.dumps(GOOD_USERS))

    import dmac_assistant.config as config_mod

    monkeypatch.setattr(config_mod, "_REPO_ROOT", empty_root, raising=False)

    from dmac_assistant.config import load_config

    cfg = load_config()
    assert set(cfg.users) == {"alice", "bob-1"}


def test_missing_users_still_raises_with_dotenv_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No DMAC_USERS in env or .env still raises (fix must not hide misconfig)."""
    empty_root = tmp_path / "no-users"
    empty_root.mkdir()

    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)

    import dmac_assistant.config as config_mod

    monkeypatch.setattr(config_mod, "_REPO_ROOT", empty_root, raising=False)

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="DMAC_USERS"):
        load_config()


# ---------------------------------------------------------------------------
# B17c: catalog_file resolution tests (D-NEW-2, D-NEW-7)
#
# Test isolation contract: every test below sets ALL bridge-required env vars
# explicitly, NOT via ambient ~/.env. _BRIDGE_REQUIRED is cross-checked against
# BridgeConfig's actual fields:
#   users (DMAC_USERS), claude_users_root (DMAC_CLAUDE_USERS_ROOT),
#   scratch_root (DMAC_SCRATCH_ROOT), dropbox_root (DMAC_DROPBOX_ROOT),
#   output_root (DMAC_OUTPUT_ROOT), catalog_file (DMAC_CATALOG_FILE_HOST_PATH),
#   plus optional bridge_host / bridge_port.
# ---------------------------------------------------------------------------


_BRIDGE_REQUIRED = {
    "DMAC_USERS": json.dumps(GOOD_USERS),
    "DMAC_CLAUDE_USERS_ROOT": "/tmp/claude-users-fake",
    "DMAC_SCRATCH_ROOT": "/tmp/scratch-fake",
    "DMAC_DROPBOX_ROOT": "/tmp/dropbox-fake",
    "DMAC_OUTPUT_ROOT": "/tmp/output-fake",
}


def _set_required_bridge_vars(
    monkeypatch: pytest.MonkeyPatch, **overrides: str | None
) -> None:
    """Set every required bridge env var deterministically.

    Each B17c test calls this BEFORE load_config() so disk .env is irrelevant.
    `overrides` lets a test omit a var (pass None) or change its value.
    """
    for k, v in _BRIDGE_REQUIRED.items():
        if k in overrides:
            override_value = overrides[k]
            if override_value is None:
                monkeypatch.delenv(k, raising=False)
                continue
            monkeypatch.setenv(k, override_value)
        else:
            monkeypatch.setenv(k, v)


@pytest.fixture
def b17c_clean_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> pytest.MonkeyPatch:
    """Isolated env for catalog_file tests (no defaults, no ambient .env)."""
    for var in (
        "DMAC_DEV_MODE",
        "DMAC_USERS",
        "DMAC_CLAUDE_USERS_ROOT",
        "DMAC_SCRATCH_ROOT",
        "DMAC_DROPBOX_ROOT",
        "DMAC_OUTPUT_ROOT",
        "DMAC_CATALOG_FILE_HOST_PATH",
        "DMAC_BRIDGE_HOST",
        "DMAC_BRIDGE_PORT",
    ):
        monkeypatch.delenv(var, raising=False)

    import dmac_assistant.config as config_mod

    isolated = tmp_path / "no_dotenv_here"
    isolated.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", isolated, raising=False)
    return monkeypatch


def test_bridge_config_resolves_catalog_file_from_env(
    b17c_clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DMAC_CATALOG_FILE_HOST_PATH overrides the dev default."""
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    _set_required_bridge_vars(b17c_clean_env)
    b17c_clean_env.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(catalog))

    from dmac_assistant.config import load_config

    cfg = load_config()
    assert cfg.catalog_file == catalog


def test_bridge_config_rejects_missing_catalog_file(
    b17c_clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-existent path raises ConfigError."""
    _set_required_bridge_vars(b17c_clean_env)
    b17c_clean_env.setenv(
        "DMAC_CATALOG_FILE_HOST_PATH", str(tmp_path / "nope.json")
    )

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(
        ConfigError,
        match="catalog_file does not exist|DMAC_CATALOG_FILE_HOST_PATH does not exist",
    ):
        load_config()


def test_bridge_config_rejects_malformed_catalog_json(
    b17c_clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B17c D-NEW-7: malformed JSON at boot raises ConfigError, not deferred to container."""
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text("{this is not json", encoding="utf-8")
    _set_required_bridge_vars(b17c_clean_env)
    b17c_clean_env.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(catalog))

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="catalog_file is not valid JSON"):
        load_config()


def test_bridge_config_dev_mode_uses_vendored_default(
    b17c_clean_env: pytest.MonkeyPatch,
) -> None:
    """In DMAC_DEV_MODE=true, missing env resolves to vendor/chat_nextseek/agent_model_catalog.json.

    Requires the vendored chat_nextseek tree (scripts/sync-vendor-deps.sh).
    """
    _set_required_bridge_vars(b17c_clean_env)
    b17c_clean_env.setenv("DMAC_DEV_MODE", "true")
    b17c_clean_env.delenv("DMAC_CATALOG_FILE_HOST_PATH", raising=False)

    # The dev-default is repo-anchored, not _REPO_ROOT-monkeypatched (b17c_clean_env
    # patches _REPO_ROOT to a tmp dir that has no vendor/). Restore the real one.
    import dmac_assistant.config as config_mod

    real_repo_root = Path(config_mod.__file__).resolve().parent.parent.parent
    real_default = (
        real_repo_root / "vendor" / "chat_nextseek" / "agent_model_catalog.json"
    )
    if not real_default.is_file():
        pytest.skip(
            "vendor/chat_nextseek/agent_model_catalog.json missing; run "
            "scripts/sync-vendor-deps.sh"
        )
    b17c_clean_env.setattr(config_mod, "_REPO_ROOT", real_repo_root, raising=False)
    b17c_clean_env.setattr(
        config_mod, "_DEV_DEFAULT_CATALOG_FILE", real_default, raising=False
    )

    from dmac_assistant.config import load_config

    cfg = load_config()
    assert cfg.catalog_file.name == "agent_model_catalog.json"
    assert cfg.catalog_file.parts[-3:] == (
        "vendor",
        "chat_nextseek",
        "agent_model_catalog.json",
    )


def test_bridge_config_field_validator_rejects_missing_catalog_file(tmp_path):
    """Direct BridgeConfig construction also gates catalog_file existence."""
    from pydantic import ValidationError

    from dmac_assistant.config import BridgeConfig, UserRecord

    catalog = tmp_path / "missing_catalog.json"
    with pytest.raises(ValidationError, match="catalog_file does not exist"):
        BridgeConfig(
            users={"alice": UserRecord(password="x", projects=["p"])},
            claude_users_root=tmp_path / "cu",
            scratch_root=tmp_path / "sc",
            dropbox_root=tmp_path / "db",
            output_root=tmp_path / "out",
            catalog_file=catalog,
        )


def test_bridge_config_field_validator_rejects_malformed_catalog_json(tmp_path):
    """Direct BridgeConfig construction also gates catalog_file JSON shape."""
    from pydantic import ValidationError

    from dmac_assistant.config import BridgeConfig, UserRecord

    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ValidationError, match="catalog_file is not valid JSON"):
        BridgeConfig(
            users={"alice": UserRecord(password="x", projects=["p"])},
            claude_users_root=tmp_path / "cu",
            scratch_root=tmp_path / "sc",
            dropbox_root=tmp_path / "db",
            output_root=tmp_path / "out",
            catalog_file=catalog,
        )


def test_bridge_config_non_dev_requires_catalog_env(
    b17c_clean_env: pytest.MonkeyPatch,
) -> None:
    """Production-like load with no env raises ConfigError."""
    _set_required_bridge_vars(b17c_clean_env)
    b17c_clean_env.delenv("DMAC_DEV_MODE", raising=False)
    b17c_clean_env.delenv("DMAC_CATALOG_FILE_HOST_PATH", raising=False)

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="DMAC_CATALOG_FILE_HOST_PATH is required"):
        load_config()


def test_dotenv_loaded_before_config_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_dotenv runs before the DMAC_USERS guard so misconfig still loads .env first."""
    import dmac_assistant.config as config_mod

    dotenv_calls: list[object] = []

    def recording_load_dotenv(*args: object, **kwargs: object) -> bool:
        dotenv_calls.append((args, kwargs))
        return False

    monkeypatch.setattr(config_mod, "load_dotenv", recording_load_dotenv)

    for var in ("DMAC_USERS",):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config_mod, "_REPO_ROOT", tmp_path, raising=False)

    from dmac_assistant.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="DMAC_USERS"):
        load_config()

    assert dotenv_calls, "load_dotenv must run before ConfigError for missing DMAC_USERS"
