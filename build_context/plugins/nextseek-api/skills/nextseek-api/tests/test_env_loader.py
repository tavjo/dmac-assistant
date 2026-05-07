"""Tests for env_loader.load_environment.

Covers:
- Canonical env var precedence (DD-07)
- Legacy fallback
- USE_DEV_API truthy override (DD-07 + Phase 2B.9.1)
- Missing credentials -> EnvMissingError
- Missing .env file path -> EnvMissingError
- Default dev vs prod base URL when nothing is set
- Interactive prompt helper (mocked input)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from lib.env_loader import (
    DEFAULT_DEV_BASE_URL,
    DEFAULT_PROD_BASE_URL,
    EnvMissingError,
    canonicalize_endpoint,
    detect_env_mismatch,
    load_environment,
    prompt_for_env_interactive,
    resolve_base_url,
)
from lib.nextseek_client import NextseekConfig


# ─── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def tmp_env_file(tmp_path: Path):
    """Factory fixture that writes a .env file from a dict and returns its path."""
    def _make(values: dict[str, str]) -> Path:
        path = tmp_path / ".env"
        lines = [f"{k}={v}" for k, v in values.items()]
        path.write_text("\n".join(lines) + "\n")
        return path
    return _make


@pytest.fixture(autouse=True)
def clean_env():
    """Wipe all potentially interfering env vars before each test."""
    keys = [
        "NEXTSEEK_BASE_URL", "API_BASE_URL", "BASE_URL", "BASE_URL_DEV",
        "USE_DEV_API",
        "SEEK_USER", "SEEK_PASSWORD",
        "username", "password",
        "NEXTSEEK_CLIENT_TIMEOUT", "NEXTSEEK_CLIENT_MAX_RETRIES",
    ]
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in keys:
            os.environ.pop(k, None)
        yield


# ─── tests ────────────────────────────────────────────────────────


def test_canonical_vars_loaded(tmp_env_file):
    """Only canonical names in .env -> correct NextseekConfig."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu/nextseek_api",
        "SEEK_USER": "canon-user",
        "SEEK_PASSWORD": "canon-pass",
    })

    cfg = load_environment(env_path)

    assert isinstance(cfg, NextseekConfig)
    assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"
    assert cfg.username == "canon-user"
    assert cfg.password == "canon-pass"


def test_legacy_vars_fallback(tmp_env_file):
    """Only legacy names in .env -> fallback loads correctly."""
    env_path = tmp_env_file({
        "API_BASE_URL": "https://nextseek-dev.mit.edu/nextseek_api",
        "username": "legacy-user",
        "password": "legacy-pass",
    })

    cfg = load_environment(env_path)

    assert cfg.base_url == "https://nextseek-dev.mit.edu/nextseek_api"
    assert cfg.username == "legacy-user"
    assert cfg.password == "legacy-pass"


def test_canonical_takes_precedence(tmp_env_file):
    """When both canonical and legacy are present, canonical wins."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://canon.example.com/api",
        "API_BASE_URL": "https://legacy.example.com/api",
        "SEEK_USER": "canon-user",
        "username": "legacy-user",
        "SEEK_PASSWORD": "canon-pass",
        "password": "legacy-pass",
    })

    cfg = load_environment(env_path)

    # After task-01, base URLs are canonicalized to always end in /nextseek_api.
    assert cfg.base_url == "https://canon.example.com/api/nextseek_api"
    assert cfg.username == "canon-user"
    assert cfg.password == "canon-pass"


def test_use_dev_api_overrides_base_url(tmp_env_file):
    """USE_DEV_API=true forces the dev URL even if NEXTSEEK_BASE_URL is set to prod."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu/nextseek_api",  # prod
        "BASE_URL_DEV": "https://nextseek-dev.mit.edu/nextseek_api",
        "USE_DEV_API": "true",
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
    })

    cfg = load_environment(env_path)

    # USE_DEV_API wins: base_url should be dev
    assert cfg.base_url == "https://nextseek-dev.mit.edu/nextseek_api"


def test_use_dev_api_falls_back_to_default_dev_when_no_base_url_dev(tmp_env_file):
    """USE_DEV_API=true without BASE_URL_DEV falls back to hardcoded DEFAULT_DEV_BASE_URL."""
    env_path = tmp_env_file({
        "USE_DEV_API": "yes",
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
    })

    cfg = load_environment(env_path)

    assert cfg.base_url == DEFAULT_DEV_BASE_URL


def test_missing_creds_raises(tmp_env_file):
    """No user AND no password anywhere -> EnvMissingError."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu/nextseek_api",
        # No creds
    })

    with pytest.raises(EnvMissingError) as exc_info:
        load_environment(env_path)

    msg = str(exc_info.value)
    assert "SEEK_USER" in msg or "credentials" in msg.lower()


def test_env_file_not_found():
    """Bogus path -> EnvMissingError with path in message."""
    bogus_path = Path("/tmp/definitely-does-not-exist-9f8e7d6c.env")

    with pytest.raises(EnvMissingError) as exc_info:
        load_environment(bogus_path)

    assert str(bogus_path) in str(exc_info.value)


def test_default_base_url_dev_vs_prod(tmp_env_file):
    """When no base URL env vars are set: use_dev=False -> prod default; use_dev=True -> dev default."""
    env_path = tmp_env_file({
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
    })

    cfg_prod = load_environment(env_path, use_dev=False)
    assert cfg_prod.base_url == DEFAULT_PROD_BASE_URL

    cfg_dev = load_environment(env_path, use_dev=True)
    assert cfg_dev.base_url == DEFAULT_DEV_BASE_URL


# ─── additional tests for coverage ────────────────────────────────


def test_use_dev_api_falsy_values_do_not_override(tmp_env_file):
    """USE_DEV_API=false/0/no/'' does not trigger the override."""
    for value in ["false", "0", "no", "", "False"]:
        env_path = tmp_env_file({
            "NEXTSEEK_BASE_URL": "https://canon.example.com/api",
            "USE_DEV_API": value,
            "SEEK_USER": "u",
            "SEEK_PASSWORD": "p",
        })
        cfg = load_environment(env_path)
        assert cfg.base_url == "https://canon.example.com/api/nextseek_api", \
            f"USE_DEV_API={value!r} should not override"


def test_missing_only_password_still_raises(tmp_env_file):
    """User present but no password -> EnvMissingError."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://x.example.com/api",
        "SEEK_USER": "alice",
    })

    with pytest.raises(EnvMissingError):
        load_environment(env_path)


def test_missing_only_user_still_raises(tmp_env_file):
    """Password present but no user -> EnvMissingError."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://x.example.com/api",
        "SEEK_PASSWORD": "secret",
    })

    with pytest.raises(EnvMissingError):
        load_environment(env_path)


def test_env_path_none_uses_process_env_only(tmp_env_file):
    """load_environment(None) reads only os.environ, not any .env file."""
    with mock.patch.dict(os.environ, {
        "NEXTSEEK_BASE_URL": "https://process-env.example.com/api",
        "SEEK_USER": "proc-user",
        "SEEK_PASSWORD": "proc-pass",
    }):
        cfg = load_environment(None)

    assert cfg.base_url == "https://process-env.example.com/api/nextseek_api"
    assert cfg.username == "proc-user"
    assert cfg.password == "proc-pass"


def test_prompt_for_env_interactive_roundtrip():
    """prompt_for_env_interactive returns a NextseekConfig from typed input."""
    inputs = iter([
        "https://nextseek.mit.edu/nextseek_api",  # base_url
        "interactive-user",                       # username
        "interactive-pass",                       # password
    ])
    with mock.patch("builtins.input", lambda prompt="": next(inputs)):
        # Mock getpass too in case the implementation uses it for password
        with mock.patch("lib.env_loader.getpass", lambda prompt="": "interactive-pass"):
            cfg = prompt_for_env_interactive()

    assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"
    assert cfg.username == "interactive-user"
    assert cfg.password == "interactive-pass"


def test_load_environment_reads_timeout_and_retries(tmp_env_file):
    """Optional NEXTSEEK_CLIENT_TIMEOUT and NEXTSEEK_CLIENT_MAX_RETRIES are honored."""
    env_path = tmp_env_file({
        "NEXTSEEK_BASE_URL": "https://x.example.com/api",
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
        "NEXTSEEK_CLIENT_TIMEOUT": "60.0",
        "NEXTSEEK_CLIENT_MAX_RETRIES": "5",
    })

    cfg = load_environment(env_path)

    assert cfg.timeout == 60.0
    assert cfg.max_retries == 5


def test_bad_timeout_falls_back_to_30(tmp_env_file):
    """Non-numeric NEXTSEEK_CLIENT_TIMEOUT falls back to 30.0."""
    env_path = tmp_env_file({
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
        "NEXTSEEK_CLIENT_TIMEOUT": "not-a-number",
    })
    cfg = load_environment(env_path)
    assert cfg.timeout == 30.0


def test_bad_retries_falls_back_to_3(tmp_env_file):
    """Non-numeric NEXTSEEK_CLIENT_MAX_RETRIES falls back to 3."""
    env_path = tmp_env_file({
        "SEEK_USER": "u",
        "SEEK_PASSWORD": "p",
        "NEXTSEEK_CLIENT_MAX_RETRIES": "nope",
    })
    cfg = load_environment(env_path)
    assert cfg.max_retries == 3


def test_prompt_interactive_empty_base_url_uses_default():
    """Empty base_url input in interactive mode falls back to DEFAULT_PROD_BASE_URL."""
    inputs = iter([
        "",                  # base_url -> empty -> default
        "interactive-user",  # username
        "interactive-pass",  # password
    ])
    with mock.patch("builtins.input", lambda prompt="": next(inputs)):
        with mock.patch("lib.env_loader.getpass", lambda prompt="": "interactive-pass"):
            cfg = prompt_for_env_interactive()

    assert cfg.base_url == DEFAULT_PROD_BASE_URL
    assert cfg.username == "interactive-user"


# ─── task-01: URL canonicalization + precedence + mismatch ──────


class TestBaseUrlCanonicalization:
    def test_canonical_with_suffix(self, tmp_env_file):
        env = tmp_env_file({
            "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu/nextseek_api",
            "SEEK_USER": "u",
            "SEEK_PASSWORD": "p",
        })
        cfg = load_environment(env)
        assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"

    def test_canonical_without_suffix(self, tmp_env_file):
        env = tmp_env_file({
            "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu",
            "SEEK_USER": "u",
            "SEEK_PASSWORD": "p",
        })
        cfg = load_environment(env)
        assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"

    def test_canonical_with_trailing_slash(self, tmp_env_file):
        env = tmp_env_file({
            "NEXTSEEK_BASE_URL": "https://nextseek.mit.edu/nextseek_api/",
            "SEEK_USER": "u",
            "SEEK_PASSWORD": "p",
        })
        cfg = load_environment(env)
        assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"

    def test_canonical_api_base_url_legacy(self, tmp_env_file):
        env = tmp_env_file({
            "API_BASE_URL": "https://nextseek.mit.edu",
            "SEEK_USER": "u",
            "SEEK_PASSWORD": "p",
        })
        cfg = load_environment(env)
        assert cfg.base_url == "https://nextseek.mit.edu/nextseek_api"


class TestCanonicalizeEndpoint:
    @pytest.mark.parametrize("inp,expected", [
        ("assays/", "assays/"),
        ("/nextseek_api/assays/", "assays/"),
        ("/assays/", "assays/"),
        ("nextseek_api/assays/", "assays/"),
        ("schema_rag/retrieve/", "schema_rag/retrieve/"),
    ])
    def test_strips_prefix(self, inp, expected):
        assert canonicalize_endpoint(inp) == expected


class TestResolveBaseUrl:
    def test_nextseek_wins_over_api(self, monkeypatch):
        monkeypatch.setenv("NEXTSEEK_BASE_URL", "https://a.example/nextseek_api")
        monkeypatch.setenv("API_BASE_URL", "https://b.example/nextseek_api")
        url, source = resolve_base_url({}, use_dev=False)
        assert url == "https://a.example/nextseek_api"
        assert source == "NEXTSEEK_BASE_URL"

    def test_use_dev_hard_override(self, monkeypatch):
        monkeypatch.setenv("NEXTSEEK_BASE_URL", "https://nextseek.mit.edu/nextseek_api")
        monkeypatch.setenv("USE_DEV_API", "1")
        url, source = resolve_base_url({}, use_dev=False)
        assert "nextseek-dev" in url
        assert source == "USE_DEV_API"

    def test_api_base_url_wins_when_no_nextseek(self, monkeypatch):
        monkeypatch.setenv("API_BASE_URL", "https://b.example/nextseek_api")
        monkeypatch.setenv("BASE_URL", "https://c.example/nextseek_api")
        url, source = resolve_base_url({}, use_dev=False)
        assert url == "https://b.example/nextseek_api"
        assert source == "API_BASE_URL"

    def test_default_fallback_prod(self):
        url, source = resolve_base_url({}, use_dev=False)
        assert url == DEFAULT_PROD_BASE_URL
        assert source == "default"

    def test_default_fallback_dev(self):
        url, source = resolve_base_url({}, use_dev=True)
        assert url == DEFAULT_DEV_BASE_URL
        assert source == "default"


class TestEnvMismatchDetection:
    def test_prod_host_dev_selection(self):
        assert detect_env_mismatch(
            "https://nextseek.mit.edu/nextseek_api", "dev",
        ) == "prod-dev"

    def test_dev_host_prod_selection(self):
        assert detect_env_mismatch(
            "https://nextseek-dev.mit.edu/nextseek_api", "prod",
        ) == "dev-prod"

    def test_matching(self):
        assert detect_env_mismatch(
            "https://nextseek.mit.edu/nextseek_api", "prod",
        ) == "match"

    def test_matching_dev(self):
        assert detect_env_mismatch(
            "https://nextseek-dev.mit.edu/nextseek_api", "dev",
        ) == "match"

    def test_unknown_host(self):
        assert detect_env_mismatch(
            "https://foo.bar/nextseek_api", "prod",
        ) == "unknown-host"


def test_prompt_interactive_missing_creds_raises():
    """Interactive prompt with empty username raises EnvMissingError."""
    inputs = iter([
        "https://nextseek.mit.edu/nextseek_api",  # base_url
        "",                                        # username -> empty
    ])
    with mock.patch("builtins.input", lambda prompt="": next(inputs)):
        with mock.patch("lib.env_loader.getpass", lambda prompt="": ""):
            with pytest.raises(EnvMissingError, match="aborted"):
                prompt_for_env_interactive()
