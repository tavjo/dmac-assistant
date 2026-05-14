"""Tests for scripts/session_status.py — the ``nextseek-session`` backing module.

Behavioral contract for DD-15 (task-02 / issue #17): the shim must
surface session TTL and expiry without mutating any cache state.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import session_status
from session_status import report_session


def _write_session_json(cache_base: Path, env: str, payload: dict) -> Path:
    env_dir = cache_base / env
    env_dir.mkdir(parents=True, exist_ok=True)
    path = env_dir / "session.json"
    path.write_text(json.dumps(payload, default=str))
    return path


@pytest.fixture
def cache_base(tmp_path: Path) -> Path:
    """Isolated cache base (no XDG interaction). Tests pass this explicitly."""
    return tmp_path / "nextseek-api"


def test_report_session_healthy(cache_base: Path) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    _write_session_json(
        cache_base,
        env="prod",
        payload={
            "session_id": "abc",
            "expires_at": expires.isoformat(),
            "base_url": "https://nextseek.mit.edu/nextseek_api",
            "env_tag": "prod",
            "schema_url": "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
        },
    )

    result = report_session("prod", cache_base=cache_base)

    assert result["status"] == "ok"
    assert result["expired"] is False
    assert result["session_id"] == "abc"
    # 30 minutes == 1800s; allow a small margin for test runtime.
    assert 1700 <= result["remaining_ttl_seconds"] <= 1800
    assert result["cache_path"].endswith("/prod/session.json")


def test_report_session_expired(cache_base: Path) -> None:
    expires = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_session_json(
        cache_base,
        env="prod",
        payload={
            "session_id": "x",
            "expires_at": expires.isoformat(),
            "base_url": "https://nextseek.mit.edu/nextseek_api",
            "env_tag": "prod",
            "schema_url": "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
        },
    )

    result = report_session("prod", cache_base=cache_base)

    assert result["status"] == "ok"
    assert result["expired"] is True
    assert result["remaining_ttl_seconds"] < 0


def test_report_session_missing(cache_base: Path) -> None:
    result = report_session("prod", cache_base=cache_base)

    assert result == {
        "status": "no-session",
        "env": "prod",
        "cache_path": str(cache_base / "prod" / "session.json"),
    }


def test_report_session_corrupt_json(cache_base: Path) -> None:
    env_dir = cache_base / "dev"
    env_dir.mkdir(parents=True)
    (env_dir / "session.json").write_text("not valid json{{{")

    result = report_session("dev", cache_base=cache_base)

    assert result["status"] == "corrupt"
    assert result["env"] == "dev"
    assert "error" in result


def test_report_session_missing_expires_at(cache_base: Path) -> None:
    _write_session_json(
        cache_base,
        env="dev",
        payload={"session_id": "x"},  # missing expires_at
    )

    result = report_session("dev", cache_base=cache_base)

    assert result["status"] == "corrupt"
    assert "invalid expires_at" in result["error"]


def test_report_session_naive_expires_at_treated_as_utc(cache_base: Path) -> None:
    """Timezone-naive ISO strings get UTC; tested so no silent wrong math slips in."""
    future_naive = (
        datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    ).isoformat()
    _write_session_json(
        cache_base,
        env="prod",
        payload={
            "session_id": "naive",
            "expires_at": future_naive,
            "base_url": "https://x",
            "env_tag": "prod",
            "schema_url": "https://x/schema",
        },
    )

    result = report_session("prod", cache_base=cache_base)
    assert result["status"] == "ok"
    assert result["expired"] is False
    assert 500 <= result["remaining_ttl_seconds"] <= 600


def test_report_session_honors_xdg_cache_home_when_cache_base_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cache_base is omitted, the plugin's resolve_plugin_cache_base() is used."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    # No session.json written — we just want to verify the resolved path.
    result = report_session("dev")
    assert result["status"] == "no-session"
    assert result["cache_path"] == str(
        tmp_path / "nextseek-api" / "v2" / "dev" / "session.json"
    )


# ---------------------------------------------------------------------------
# main() CLI wrapper
# ---------------------------------------------------------------------------


def test_main_healthy_returns_zero(
    cache_base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Inject our cache_base by monkeypatching resolve_plugin_cache_base.
    monkeypatch.setattr(
        session_status, "resolve_plugin_cache_base", lambda: cache_base
    )
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    _write_session_json(
        cache_base,
        env="prod",
        payload={
            "session_id": "abc",
            "expires_at": expires.isoformat(),
            "base_url": "https://nextseek.mit.edu/nextseek_api",
            "env_tag": "prod",
            "schema_url": "https://x/schema",
        },
    )

    exit_code = session_status.main(["--env", "prod"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "status: ok" in out
    assert "session_id: abc" in out
    assert "expired: False" in out


def test_main_missing_returns_nonzero(
    cache_base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        session_status, "resolve_plugin_cache_base", lambda: cache_base
    )
    exit_code = session_status.main(["--env", "prod"])
    assert exit_code == 1
    assert "status: no-session" in capsys.readouterr().out


def test_main_expired_returns_nonzero(
    cache_base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        session_status, "resolve_plugin_cache_base", lambda: cache_base
    )
    expires = datetime.now(timezone.utc) - timedelta(minutes=1)
    _write_session_json(
        cache_base,
        env="prod",
        payload={
            "session_id": "x",
            "expires_at": expires.isoformat(),
            "base_url": "https://x",
            "env_tag": "prod",
            "schema_url": "https://x/schema",
        },
    )

    exit_code = session_status.main(["--env", "prod"])

    assert exit_code == 1
    assert "expired: True" in capsys.readouterr().out


def test_main_json_output(
    cache_base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        session_status, "resolve_plugin_cache_base", lambda: cache_base
    )
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    _write_session_json(
        cache_base,
        env="dev",
        payload={
            "session_id": "jid",
            "expires_at": expires.isoformat(),
            "base_url": "https://x",
            "env_tag": "dev",
            "schema_url": "https://x/schema",
        },
    )

    exit_code = session_status.main(["--env", "dev", "--json"])

    assert exit_code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["status"] == "ok"
    assert parsed["session_id"] == "jid"
    assert parsed["env"] == "dev"
