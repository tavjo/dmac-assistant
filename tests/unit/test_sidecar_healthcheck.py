"""Host-side healthcheck tests with fake mysql.connector module."""
import sys
from types import ModuleType

import pytest


def _install_fake_mysql(monkeypatch, *, connect_ok: bool = True):
    fake = ModuleType("mysql")
    connector = ModuleType("mysql.connector")

    class FakeCursor:
        def execute(self, _sql):
            return None

        def fetchall(self):
            return [(1,)]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    def connect(**_kwargs):
        if not connect_ok:
            raise OSError("connection refused")
        return FakeConn()

    connector.connect = connect
    fake.connector = connector
    monkeypatch.setitem(sys.modules, "mysql", fake)
    monkeypatch.setitem(sys.modules, "mysql.connector", connector)


def test_healthcheck_ok(monkeypatch, tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text('[{"method": "GET", "path": "/x"}]', encoding="utf-8")
    for key, val in {
        "SESSION_DB_HOST": "db.example",
        "SESSION_DB_USER": "u",
        "SESSION_DB_PASSWORD": "p",
        "SESSION_DB_NAME": "n",
        "SIDECAR_STAGING_DIR": "/staging",
        "READ_SAFE_ENDPOINTS_PATH": str(allowlist),
    }.items():
        monkeypatch.setenv(key, val)
    _install_fake_mysql(monkeypatch)
    from sidecar.app import healthcheck

    assert healthcheck.main() == 0


def test_healthcheck_fails_on_empty_allowlist(monkeypatch, tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text("[]", encoding="utf-8")
    for key, val in {
        "SESSION_DB_HOST": "db.example",
        "SESSION_DB_USER": "u",
        "SESSION_DB_PASSWORD": "p",
        "SESSION_DB_NAME": "n",
        "SIDECAR_STAGING_DIR": "/staging",
        "READ_SAFE_ENDPOINTS_PATH": str(allowlist),
    }.items():
        monkeypatch.setenv(key, val)
    _install_fake_mysql(monkeypatch)
    from sidecar.app import healthcheck

    assert healthcheck.main() == 1


def test_healthcheck_fails_on_db_error(monkeypatch, tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text('[{"method": "GET", "path": "/x"}]', encoding="utf-8")
    for key, val in {
        "SESSION_DB_HOST": "db.example",
        "SESSION_DB_USER": "u",
        "SESSION_DB_PASSWORD": "p",
        "SESSION_DB_NAME": "n",
        "SIDECAR_STAGING_DIR": "/staging",
        "READ_SAFE_ENDPOINTS_PATH": str(allowlist),
    }.items():
        monkeypatch.setenv(key, val)
    _install_fake_mysql(monkeypatch, connect_ok=False)
    from sidecar.app import healthcheck

    assert healthcheck.main() == 1
