"""Plan A · T1: BridgeConfig must expose an output_root path field."""
from __future__ import annotations

import json

import pytest

from dmac_assistant.config import ConfigError, load_config


@pytest.fixture
def base_env(tmp_path, monkeypatch):
    users = json.dumps({"alice": {"password": "pw", "projects": ["demo"]}})
    monkeypatch.setenv("DMAC_USERS", users)
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(tmp_path / "claude"))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(tmp_path / "dropbox"))
    sidecar_staging = tmp_path / "sidecar-staging"
    sidecar_staging.mkdir()
    monkeypatch.setenv("DMAC_SIDECAR_STAGING_ROOT", str(sidecar_staging))
    monkeypatch.delenv("DMAC_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("DMAC_DEV_MODE", raising=False)
    # B17c: catalog_file is now a required BridgeConfig field; set a valid path
    # so this fixture's tests focus solely on output_root behavior.
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(catalog))
    # Isolate load_config() from the developer's real repo .env. load_config()
    # runs load_dotenv(_REPO_ROOT / ".env", override=False), which re-injects
    # DMAC_DEV_MODE=true (present in the real .env) right after the delenv above,
    # flipping the loader into dev mode and defeating the prod-required check.
    # Point _REPO_ROOT at an empty dir (matches tests/unit/test_config.py).
    import dmac_assistant.config as config_mod

    isolated = tmp_path / "no_dotenv_here"
    isolated.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", isolated, raising=False)
    return tmp_path


def test_output_root_required_in_prod(base_env):
    with pytest.raises(ConfigError, match="DMAC_OUTPUT_ROOT"):
        load_config()


def test_output_root_loaded_when_set(base_env, monkeypatch):
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(base_env / "out"))
    cfg = load_config()
    assert cfg.output_root == base_env / "out"


def test_output_root_dev_default(base_env, monkeypatch):
    monkeypatch.setenv("DMAC_DEV_MODE", "1")
    cfg = load_config()
    assert str(cfg.output_root).endswith("dmac-dev/output")
