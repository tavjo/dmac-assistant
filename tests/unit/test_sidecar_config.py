"""SidecarConfig loads from env; required keys fail loud; no secret values in repr."""
import pytest

from sidecar.app.config import SidecarConfig, SidecarConfigError

REQUIRED = {
    "SESSION_DB_HOST": "db.example",
    "SESSION_DB_USER": "u",
    "SESSION_DB_PASSWORD": "p",
    "SESSION_DB_NAME": "n",
    "SIDECAR_STAGING_DIR": "/staging",
    "READ_SAFE_ENDPOINTS_PATH": "/ctx/read_safe_endpoints.json",
}


def test_loads_from_env(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SIDECAR_WS_PORT", "8765")
    cfg = SidecarConfig.from_env()
    assert cfg.ws_port == 8765
    assert cfg.session_db["host"] == "db.example"
    assert cfg.session_db["port"] == 3306
    assert cfg.staging_dir == "/staging"


def test_missing_required_raises(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


def test_session_db_port_defaults_to_3306(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SESSION_DB_PORT", raising=False)
    cfg = SidecarConfig.from_env()
    assert cfg.session_db["port"] == 3306


def test_repr_redacts_password(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    cfg = SidecarConfig.from_env()
    assert "REDACTED" in repr(cfg)
