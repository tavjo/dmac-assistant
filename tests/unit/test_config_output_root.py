"""Plan A · T1: BridgeConfig must expose an output_root path field."""
from __future__ import annotations

import json

import pytest

from dmac_assistant.config import BridgeConfig, ConfigError, load_config


@pytest.fixture
def base_env(tmp_path, monkeypatch):
    users = json.dumps({"alice": {"password": "pw", "projects": ["demo"]}})
    monkeypatch.setenv("DMAC_USERS", users)
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(tmp_path / "claude"))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(tmp_path / "dropbox"))
    monkeypatch.delenv("DMAC_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("DMAC_DEV_MODE", raising=False)
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
