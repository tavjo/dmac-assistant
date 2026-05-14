"""Tests for lib.cache_paths.

DD-7 (task-06a): cache base is bumped to ``nextseek-api/v2/`` so that
stale pre-v2 cache dirs with camelCase contents are silently ignored.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.cache_paths import (
    resolve_endpoint_full_path,
    resolve_endpoints_full_dir,
    resolve_endpoints_minimal_path,
    resolve_env_cache_dir,
    resolve_plugin_cache_base,
    resolve_session_json_path,
)


def test_cache_base_contains_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DD-7: resolve_plugin_cache_base() returns a path containing '/v2/'."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    base = resolve_plugin_cache_base()
    assert "v2" in base.parts, f"cache base {base} must contain 'v2' per DD-7"
    assert base == tmp_path / "nextseek-api" / "v2"


def test_cache_base_defaults_to_home_cache_v2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no XDG_CACHE_HOME set, resolver falls back to ~/.cache/nextseek-api/v2/."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    base = resolve_plugin_cache_base()
    # Path.home() uses HOME on POSIX.
    assert str(base).endswith("/.cache/nextseek-api/v2")


def test_env_scoped_helpers_inherit_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All env-scoped helpers emit v2-rooted paths."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert resolve_env_cache_dir("dev") == tmp_path / "nextseek-api" / "v2" / "dev"
    assert (
        resolve_session_json_path("prod")
        == tmp_path / "nextseek-api" / "v2" / "prod" / "session.json"
    )
    assert (
        resolve_endpoints_minimal_path("dev")
        == tmp_path / "nextseek-api" / "v2" / "dev" / "endpoints_minimal.json"
    )
    assert (
        resolve_endpoints_full_dir("prod")
        == tmp_path / "nextseek-api" / "v2" / "prod" / "endpoints_full"
    )
    assert (
        resolve_endpoint_full_path("dev", "getSamples")
        == tmp_path / "nextseek-api" / "v2" / "dev" / "endpoints_full" / "getSamples.json"
    )


def test_endpoint_full_path_accepts_cache_base_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task-06b: resolve_endpoint_full_path honors an explicit cache_base kwarg."""
    # XDG points one place; override points somewhere else.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "unused"))
    override = tmp_path / "override"
    got = resolve_endpoint_full_path("dev", "GetAssay", cache_base=override)
    assert got == override / "dev" / "endpoints_full" / "GetAssay.json"


def test_endpoint_full_path_sanitizes_slashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slashes in operation_id must be replaced with underscores."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    got = resolve_endpoint_full_path("dev", "weird/op/id")
    assert got.name == "weird_op_id.json"
    assert got.parent.name == "endpoints_full"


def test_old_cache_dir_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing ~/.cache/nextseek-api/dev/ (no v2) is NOT consulted by helpers."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    # Seed a "v1" (pre-bump) cache directory with stale camelCase contents.
    old_dir = tmp_path / "nextseek-api" / "dev"
    old_dir.mkdir(parents=True)
    (old_dir / "endpoints_minimal.json").write_text(
        json.dumps({"endpoints": [{"operationId": "stale", "path": "/stale/"}]})
    )

    # The v2-rooted path is what helpers now resolve to; it is NOT the old dir.
    new_path = resolve_endpoints_minimal_path("dev")
    assert new_path != old_dir / "endpoints_minimal.json"
    assert "v2" in new_path.parts
    assert not new_path.exists(), "v2 path should be empty when only v1 is seeded"
