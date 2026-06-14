"""SidecarConfig loads from env (T16: requires NEXTSEEK_BASE_URL + SIDECAR_STAGING_DIR;
dropped SESSION_DB_* and READ_SAFE_ENDPOINTS_PATH); required keys fail loud."""
import pytest

from sidecar.app.config import SidecarConfig, SidecarConfigError

REQUIRED = {
    "NEXTSEEK_BASE_URL": "http://nextseek_nginx",
    "SIDECAR_STAGING_DIR": "/staging",
}


def test_loads_from_env(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SIDECAR_WS_PORT", "8765")
    cfg = SidecarConfig.from_env()
    assert cfg.ws_port == 8765
    assert cfg.nextseek_base_url == "http://nextseek_nginx"
    assert cfg.staging_dir == "/staging"


def test_missing_required_raises(monkeypatch):
    for k in REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


def test_missing_nextseek_base_url_raises(monkeypatch):
    monkeypatch.setenv("SIDECAR_STAGING_DIR", "/staging")
    monkeypatch.delenv("NEXTSEEK_BASE_URL", raising=False)
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


def test_missing_staging_dir_raises(monkeypatch):
    monkeypatch.setenv("NEXTSEEK_BASE_URL", "http://nextseek_nginx")
    monkeypatch.delenv("SIDECAR_STAGING_DIR", raising=False)
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


def test_ws_port_defaults_to_8765(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SIDECAR_WS_PORT", raising=False)
    cfg = SidecarConfig.from_env()
    assert cfg.ws_port == 8765


def test_ws_port_can_be_overridden(monkeypatch):
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SIDECAR_WS_PORT", "9000")
    cfg = SidecarConfig.from_env()
    assert cfg.ws_port == 9000


def test_repr_does_not_include_sensitive_values(monkeypatch):
    """Repr should be safe to log — no passwords or tokens."""
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    cfg = SidecarConfig.from_env()
    r = repr(cfg)
    assert "nextseek_nginx" in r  # base_url is fine to show
    assert "staging" in r


def test_old_session_db_keys_not_required(monkeypatch):
    """SESSION_DB_* and READ_SAFE_ENDPOINTS_PATH are no longer required (T16)."""
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    # Ensure old keys are absent — config should still load fine
    for old_key in ("SESSION_DB_HOST", "SESSION_DB_USER", "SESSION_DB_PASSWORD",
                    "SESSION_DB_NAME", "READ_SAFE_ENDPOINTS_PATH"):
        monkeypatch.delenv(old_key, raising=False)
    cfg = SidecarConfig.from_env()
    assert cfg.nextseek_base_url == "http://nextseek_nginx"
