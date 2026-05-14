"""Tests for scripts/execute_request.py -- live executor with Layer 2 safety enforcement.

SAFETY-CRITICAL. Every test in this file encodes a mitigation for Risk #1 in the
plan's Risk Register (write-safety bypass -> irreversible NExtSEEK mutation).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# conftest.py (task-01) adds scripts/ to sys.path so `from lib.X import ...`
# and `import execute_request` both resolve without sys.path hacks (CL-1).
import execute_request  # noqa: E402
from lib.cache_paths import resolve_endpoints_full_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_env_file(tmp_path: Path) -> Path:
    p = tmp_path / "fake.env"
    p.write_text(
        "NEXTSEEK_BASE_URL=https://nextseek-dev.mit.edu\n"
        "SEEK_USER=alice\n"
        "SEEK_PASSWORD=hunter2\n"
    )
    return p


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect XDG_CACHE_HOME so cache_paths helpers resolve under tmp_path (CL-7)."""
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    env_dir = resolve_endpoints_full_dir("dev")
    env_dir.mkdir(parents=True, exist_ok=True)
    return env_dir


def _write_cached_endpoint(cache_dir: Path, endpoint: dict) -> None:
    path = cache_dir / f"{endpoint['operationId']}.json"
    path.write_text(json.dumps(endpoint))


def _get_samples_endpoint() -> dict:
    """Pre-seeded FullEndpoint JSON; CL-6 list-form parameters (normalized by task-06)."""
    return {
        "operationId": "samples_list",
        "method": "GET",
        "path": "/nextseek_api/samples/",
        "summary": "List samples",
        "tags": ["samples"],
        "parameters": [],
        "request_schema": {},
        "response_schema": {"type": "object"},
    }


def _upload_samples_endpoint() -> dict:
    return {
        "operationId": "samples_upload",
        "method": "POST",
        "path": "/nextseek_api/samples/upload/",
        "summary": "Upload samples",
        "tags": ["samples"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["samples"],
            "properties": {"samples": {"type": "array"}},
        },
        "response_schema": {},
    }


def _schemarag_retrieve_endpoint() -> dict:
    return {
        "operationId": "schema_rag_retrieve",
        "method": "POST",
        "path": "/nextseek_api/schema_rag/retrieve/",
        "summary": "Retrieve endpoint metadata",
        "tags": ["schema_rag"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        "response_schema": {"type": "object"},
    }


def _admin_samples_retrieve_endpoint() -> dict:
    """POST endpoint with NO denylist terms in op_id or path -- used by test 8.

    operation_id='admin_samples_retrieve', path='/nextseek_api/admin/samples/retrieve/'.
    None of (upload|create|update|delete|remove|patch|put) appear. Layer 2 must
    still block this because it is non-GET and not under schema_rag/* (CL-8).
    """
    return {
        "operationId": "admin_samples_retrieve",
        "method": "POST",
        "path": "/nextseek_api/admin/samples/retrieve/",
        "summary": "Bulk sample retrieve by UID",
        "tags": ["admin"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["identifiers"],
            "properties": {"identifiers": {"type": "array"}},
        },
        "response_schema": {"type": "object"},
    }


@pytest.fixture
def mock_client():
    """Patch NextseekClient to a MagicMock whose context-manager exposes .request()."""
    with patch.object(execute_request, "NextseekClient") as cls:
        instance = MagicMock()
        instance.request.return_value = {"ok": True, "data": []}
        cls.return_value.__enter__.return_value = instance
        cls.return_value.__exit__.return_value = False
        yield instance


@pytest.fixture
def cached_endpoints_full_admin_retrieve(cache_root: Path) -> Path:
    """Pre-seed <env_cache>/endpoints_full/admin_samples_retrieve.json for test 8 (CL-8).

    The FullEndpoint has method=POST, path=/admin/samples/retrieve/, and NO denylist
    terms in operation_id or path. This proves Layer 2 blocks a non-denylisted POST
    purely because it is not GET and not under schema_rag/*.
    """
    _write_cached_endpoint(cache_root, _admin_samples_retrieve_endpoint())
    return cache_root / "admin_samples_retrieve.json"


# ---------------------------------------------------------------------------
# Test 1 -- happy path: GET executes successfully
# ---------------------------------------------------------------------------
def test_get_executes_successfully(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {"limit": 10},
        "request_body": None,
    }
    mock_client.request.return_value = {"results": [{"uid": "SMPL-1"}]}

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body == {"results": [{"uid": "SMPL-1"}]}
    mock_client.request.assert_called_once()
    call_args = mock_client.request.call_args
    assert call_args.args[0] == "GET"
    assert "samples" in call_args.args[1]


# ---------------------------------------------------------------------------
# Test 2 -- SAFETY: POST to /samples/upload/ without --confirmed-write is denied
# ---------------------------------------------------------------------------
def test_non_get_non_schemarag_without_confirmed_write_exits_denied(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _upload_samples_endpoint())
    spec = {
        "operation_id": "samples_upload",
        "method": "POST",
        "endpoint": "/nextseek_api/samples/upload/",
        "path_params": {},
        "query_params": {},
        "request_body": {"samples": [{"uid": "SMPL-1"}]},
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "SafetyPolicyBlocked" in err
    # CRITICAL: network call must NOT have happened.
    mock_client.request.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3 -- SAFETY opt-out: POST /samples/upload/ WITH --confirmed-write proceeds
# ---------------------------------------------------------------------------
def test_non_get_with_confirmed_write_proceeds(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _upload_samples_endpoint())
    spec = {
        "operation_id": "samples_upload",
        "method": "POST",
        "endpoint": "/nextseek_api/samples/upload/",
        "path_params": {},
        "query_params": {},
        # Body intentionally avoids suspicious terms; suspicious-body check
        # is covered separately by the validator + Layer 2 scan.
        "request_body": {"samples": [{"uid": "SMPL-1"}]},
    }
    mock_client.request.return_value = {"created": 1}

    stdin = io.StringIO(json.dumps(spec))
    argv = [
        "execute_request.py",
        "--env", "dev",
        "--env-file", str(fake_env_file),
        "--confirmed-write",
    ]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 0
    mock_client.request.assert_called_once()
    assert mock_client.request.call_args.args[0] == "POST"
    assert json.loads(capsys.readouterr().out) == {"created": 1}


# ---------------------------------------------------------------------------
# Test 4 -- SAFETY allowlist: schema_rag POST auto-allowed without flag
# ---------------------------------------------------------------------------
def test_schemarag_post_auto_allowed(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_cached_endpoint(cache_root, _schemarag_retrieve_endpoint())
    spec = {
        "operation_id": "schema_rag_retrieve",
        "method": "POST",
        "endpoint": "/nextseek_api/schema_rag/retrieve/",
        "path_params": {},
        "query_params": {},
        "request_body": {"query": "samples"},
    }
    mock_client.request.return_value = {"endpoints_full": []}

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 0, "schema_rag POST must be auto-allowed without --confirmed-write"
    mock_client.request.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5 -- auth error from client surfaces with stable exit code
# ---------------------------------------------------------------------------
def test_auth_error_exits_with_code(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lib.nextseek_client import NextseekAuthError  # noqa: WPS433

    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    mock_client.request.side_effect = NextseekAuthError("401 Unauthorized")

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "NextseekAuthError" in err


# ---------------------------------------------------------------------------
# Test 6 -- internal validator fails -> refuse execution (no HTTP call)
# ---------------------------------------------------------------------------
def test_validation_fails_refuses_execution(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Valid cached GET endpoint with a required path_param, but the spec omits it.
    endpoint = _get_samples_endpoint()
    endpoint["path"] = "/nextseek_api/samples/{uid}/"
    endpoint["parameters"] = [
        {"name": "uid", "in": "path", "required": True, "schema": {"type": "string"}}
    ]
    _write_cached_endpoint(cache_root, endpoint)

    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {},  # missing uid
        "query_params": {},
        "request_body": None,
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "validation" in err.lower() or "FAIL" in err
    mock_client.request.assert_not_called()  # CRITICAL


# ---------------------------------------------------------------------------
# Test 7 -- malformed JSON input -> exit 1 before any HTTP
# ---------------------------------------------------------------------------
def test_invalid_request_spec_json_exits_early(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stdin = io.StringIO("{this is not valid json")
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    assert exit_code == 1
    mock_client.request.assert_not_called()  # CRITICAL
    err = capsys.readouterr().err
    assert "JSON" in err or "json" in err


# ---------------------------------------------------------------------------
# Test 8 -- SAFETY: non-denylisted POST STILL blocked without --confirmed-write
# ---------------------------------------------------------------------------
# Per CL-8 / plan Section 11 amendment #6 / Risk Register #1 mitigation.
# POST to /admin/samples/retrieve/ contains NO denylist terms and is NOT under
# schema_rag/*. Layer 2 must block it anyway because the general rule is:
# non-GET + non-schema_rag requires --confirmed-write. This proves the denylist
# is defense-in-depth on TOP of the primary non-GET gate, not a replacement.
def test_non_denylisted_post_still_blocked_without_confirmed_write(
    fake_env_file: Path,
    cached_endpoints_full_admin_retrieve: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    POST to /admin/samples/retrieve/ contains no denylist terms (upload/create/etc)
    AND is not under schema_rag/*. Layer 2 must block it anyway because the general
    rule is: non-GET + non-schema_rag requires --confirmed-write.

    Proves Risk Register #1 mitigation: the denylist is a defense-in-depth layer
    on TOP of the "non-GET non-schema_rag requires confirmed-write" gate, not a
    replacement for it.
    """
    spec = {
        "operation_id": "admin_samples_retrieve",
        "method": "POST",
        "endpoint": "/nextseek_api/admin/samples/retrieve/",
        "path_params": {},
        "query_params": {},
        "headers": {},
        "request_body": {"identifiers": ["UID-123"]},
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()

    captured = capsys.readouterr()

    assert exit_code != 0, (
        "non-denylisted POST must still be blocked without --confirmed-write"
    )
    assert "SafetyPolicyBlocked" in captured.err
    # CRITICAL: Layer 2 MUST block BEFORE any network touch.
    mock_client.request.assert_not_called()


# ---------------------------------------------------------------------------
# Coverage supplemental tests (branches not reached by the 8 primary tests)
# ---------------------------------------------------------------------------


def _no_required_body_post_endpoint() -> dict:
    """POST endpoint with no required body fields and no denylist terms."""
    return {
        "operationId": "admin_samples_retrieve",
        "method": "POST",
        "path": "/nextseek_api/admin/samples/retrieve/",
        "summary": "Bulk sample retrieve by UID",
        "tags": ["admin"],
        "parameters": [],
        "request_schema": {"type": "object"},
        "response_schema": {"type": "object"},
    }


def test_suspicious_body_with_confirmed_write_proceeds(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """POST with suspicious body terms but --confirmed-write proceeds."""
    _write_cached_endpoint(cache_root, _no_required_body_post_endpoint())
    spec = {
        "operation_id": "admin_samples_retrieve",
        "method": "POST",
        "endpoint": "/nextseek_api/admin/samples/retrieve/",
        "path_params": {},
        "query_params": {},
        "headers": {},
        "request_body": {"action": "delete all records"},
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = [
        "execute_request.py", "--env", "dev", "--env-file", str(fake_env_file),
        "--confirmed-write",
    ]
    mock_client.request.return_value = {"ok": True}
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 0


def test_suspicious_body_key_triggers_block(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """POST with suspicious key name in body is blocked without --confirmed-write."""
    _write_cached_endpoint(cache_root, _no_required_body_post_endpoint())
    spec = {
        "operation_id": "admin_samples_retrieve",
        "method": "POST",
        "endpoint": "/nextseek_api/admin/samples/retrieve/",
        "path_params": {},
        "query_params": {},
        "headers": {},
        "request_body": {"delete_mode": True, "nested": {"truncate": "yes"}},
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "SuspiciousRequestBody" in err or "SafetyPolicyBlocked" in err
    mock_client.request.assert_not_called()


def test_file_input_reads_from_path(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--file flag reads RequestSpec from a file instead of stdin."""
    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    mock_client.request.return_value = {"ok": True}

    argv = [
        "execute_request.py", "--env", "dev",
        "--env-file", str(fake_env_file),
        "--file", str(spec_file),
    ]
    with patch.object(sys, "argv", argv):
        exit_code = execute_request.main()
    assert exit_code == 0


def test_pydantic_validation_error_exits_early(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valid JSON but missing required RequestSpec fields -> exit 1 before HTTP."""
    spec = {"method": "GET"}  # missing operation_id, endpoint
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 1
    err = capsys.readouterr().err
    # Pydantic ValidationError may be caught by either handler
    assert "validation" in err.lower() or "JSON" in err
    mock_client.request.assert_not_called()


def test_cache_miss_exits_with_config_error(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RequestSpec references an operation not in cache -> CACHE_MISS exit."""
    spec = {
        "operation_id": "nonexistent_op",
        "method": "GET",
        "endpoint": "/nextseek_api/nonexistent/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 3  # EXIT_CONFIG
    err = capsys.readouterr().err
    assert "CACHE_MISS" in err
    mock_client.request.assert_not_called()


def test_timeout_error_exits_with_api_code(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NextseekTimeoutError from client surfaces with EXIT_API."""
    from lib.nextseek_client import NextseekTimeoutError as TimeoutErr

    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    mock_client.request.side_effect = TimeoutErr("timed out")

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 2  # EXIT_API
    err = capsys.readouterr().err
    assert "NextseekTimeoutError" in err


def test_api_error_exits_with_api_code(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NextseekAPIError from client surfaces with EXIT_API."""
    from lib.nextseek_client import NextseekAPIError as APIErr

    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    mock_client.request.side_effect = APIErr("server error", status_code=500)

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "NextseekAPIError" in err


def test_generic_client_error_exits_with_api_code(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NextseekClientError (base) from client surfaces with EXIT_API."""
    from lib.nextseek_client import NextseekClientError as ClientErr

    _write_cached_endpoint(cache_root, _get_samples_endpoint())
    spec = {
        "operation_id": "samples_list",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/",
        "path_params": {},
        "query_params": {},
        "request_body": None,
    }
    mock_client.request.side_effect = ClientErr("connection lost")

    stdin = io.StringIO(json.dumps(spec))
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "NextseekClientError" in err


def test_empty_stdin_exits_with_json_error(
    fake_env_file: Path,
    cache_root: Path,
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty stdin -> JSON_PARSE exit."""
    stdin = io.StringIO("")
    argv = ["execute_request.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", stdin):
        exit_code = execute_request.main()
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "JSON" in err or "json" in err
    mock_client.request.assert_not_called()
