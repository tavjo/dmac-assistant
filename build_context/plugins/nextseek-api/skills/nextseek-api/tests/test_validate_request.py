"""Tests for scripts/validate_request.py — static request validator CLI."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# conftest.py (task-01) adds scripts/ to sys.path so `from lib.X import ...`
# and `import validate_request` both resolve.
import validate_request  # noqa: E402


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Monkeypatch XDG_CACHE_HOME and return the env-scoped endpoints_full dir."""
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    env_dir = cache / "nextseek-api" / "v2" / "dev" / "endpoints_full"
    env_dir.mkdir(parents=True, exist_ok=True)
    return env_dir


def _write_cached_endpoint(cache_dir: Path, endpoint: dict) -> Path:
    op_id = endpoint["operationId"]
    path = cache_dir / f"{op_id}.json"
    path.write_text(json.dumps(endpoint))
    return path


def _valid_get_endpoint() -> dict:
    """Pre-seed a FullEndpoint JSON using CL-6 list-form parameters (OpenAPI-native).

    The validator (task-06) normalizes list -> dict internally.
    """
    return {
        "operationId": "samples_get",
        "method": "GET",
        "path": "/nextseek_api/samples/{uid}/",
        "summary": "Get one sample",
        "tags": ["samples"],
        "parameters": [
            {"name": "uid", "in": "path", "required": True, "schema": {"type": "string"}},
        ],
        "request_schema": {},
        "response_schema": {"type": "object"},
    }


def _delete_endpoint() -> dict:
    return {
        "operationId": "samples_delete",
        "method": "POST",
        "path": "/nextseek_api/samples/delete/",
        "summary": "Delete samples",
        "tags": ["samples"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["uid"],
            "properties": {"uid": {"type": "string"}},
        },
        "response_schema": None,
    }


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def test_valid_spec_exits_0(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _valid_get_endpoint())
    spec = {
        "operation_id": "samples_get",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "SMPL-1"},
        "query_params": {},
        "request_body": None,
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["status"] == "PASS"
    assert result["spec"]["operation_id"] == "samples_get"


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------
def test_invalid_spec_exits_1_with_errors(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _valid_get_endpoint())
    # Missing required path_param {uid}.
    spec = {
        "operation_id": "samples_get",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    assert isinstance(result["errors"], list) and len(result["errors"]) >= 1
    assert any("uid" in str(e).lower() or "path" in str(e).lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------
def test_missing_cached_endpoint_exits_2(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Do NOT pre-seed the cache.
    spec = {
        "operation_id": "samples_get",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "SMPL-1"},
        "query_params": {},
        "request_body": None,
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "Run fetch_spec.py first" in err
    assert "samples_get" in err


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------
def test_reads_from_file_flag(
    cache_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _valid_get_endpoint())
    spec = {
        "operation_id": "samples_get",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "SMPL-1"},
        "query_params": {},
        "request_body": None,
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    # --file takes precedence; leave stdin empty to prove it isn't consulted.
    stdin = io.StringIO("")
    argv = ["validate_request.py", "--env", "dev", "--file", str(spec_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert json.loads(out)["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 5
# ---------------------------------------------------------------------------
def test_denylist_block_exits_1_with_specific_error_code(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _delete_endpoint())
    spec = {
        "operation_id": "samples_delete",
        "method": "POST",
        "endpoint": "/nextseek_api/samples/delete/",
        "path_params": {},
        "query_params": {},
        "request_body": {"uid": "SMPL-1"},
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    codes = [e.get("code") for e in result["errors"] if isinstance(e, dict)]
    assert "DENYLIST_BLOCK" in codes


# ---------------------------------------------------------------------------
# Test 6 — malformed JSON input
# ---------------------------------------------------------------------------
def test_malformed_json_exits_1_with_json_parse_code(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stdin = io.StringIO("not valid json{{{")
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    codes = [e.get("code") for e in result["errors"] if isinstance(e, dict)]
    assert "JSON_PARSE" in codes


# ---------------------------------------------------------------------------
# Test 7 — empty stdin input
# ---------------------------------------------------------------------------
def test_empty_stdin_exits_1_with_json_parse_code(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stdin = io.StringIO("")
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    codes = [e.get("code") for e in result["errors"] if isinstance(e, dict)]
    assert "JSON_PARSE" in codes


# ---------------------------------------------------------------------------
# Test 8 — invalid RequestSpec (pydantic validation failure, humanized)
# ---------------------------------------------------------------------------
def test_invalid_request_spec_schema_exits_1_with_humanized_errors(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Valid JSON but missing required fields for RequestSpec
    spec = {"operation_id": "foo"}  # missing method, endpoint
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    # Humanized errors have location/code/message keys (code is the pydantic type)
    errors = result["errors"]
    assert len(errors) >= 1
    for e in errors:
        assert "location" in e
        assert "code" in e
        assert "message" in e
    # expect missing fields: method, endpoint
    locations = [e["location"] for e in errors]
    assert any("method" in loc for loc in locations)
    assert any("endpoint" in loc for loc in locations)


# ---------------------------------------------------------------------------
# Test 9 — camelCase field yields hint
# ---------------------------------------------------------------------------
def test_camelcase_operationid_yields_hint(
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = {"operationId": "X", "method": "GET", "endpoint": "a/"}
    stdin = io.StringIO(json.dumps(spec))
    argv = ["validate_request.py", "--env", "dev"]

    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = validate_request.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["ok"] is False
    # One error should be located at $.operationId and have a hint
    locs = [e["location"] for e in result["errors"]]
    assert any(loc == "$.operationId" for loc in locs)
    hinted = [e for e in result["errors"] if e.get("hint")]
    assert any("operation_id" in e["hint"] for e in hinted)
