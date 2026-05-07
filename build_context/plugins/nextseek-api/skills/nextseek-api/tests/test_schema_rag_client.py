"""Tests for SchemaRAGClient: sync port with persistent disk cache.

These tests are the authoritative behavioral contract for task-05.
The implementation in scripts/lib/schema_rag_client.py must satisfy
every assertion without modification.

Imports use the `from lib.X` convention (CL-1). The top-level
skills/nextseek-api/tests/conftest.py (created by task-01) injects
`scripts/` onto sys.path so `lib.*` resolves.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from lib.schema_rag_client import SchemaRAGClient
from lib.models import (
    FullEndpoint,
    IngestResponse,
    MinimalEndpoint,
    SchemaRAGResponse,
    SessionState,
)
from lib.nextseek_client import NextseekAuthError, SessionExpiredError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_schema_url() -> str:
    return "https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml"


@pytest.fixture
def fake_base_url() -> str:
    """Base URL matching fake_schema_url's host (CL-3/CL-4 require base_url)."""
    return "https://nextseek-dev.mit.edu/nextseek_api"


@pytest.fixture
def future_iso() -> str:
    """ISO-8601 timestamp 30 minutes in the future (UTC)."""
    return (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()


@pytest.fixture
def past_iso() -> str:
    """ISO-8601 timestamp 10 minutes in the past (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()


@pytest.fixture
def mock_http_client() -> MagicMock:
    """A MagicMock standing in for a sync NextseekClient."""
    client = MagicMock(name="NextseekClient")
    return client


def _ingest_payload(session_id: str, expires_at: str, num_endpoints: int = 120) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "schema_url": "https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml",
        "ttl_minutes": 30,
        "expires_at": expires_at,
        "num_endpoints": num_endpoints,
    }


def _minimal_retrieve_payload() -> dict[str, Any]:
    return {
        "session_id": "sid-abc",
        "mode": "minimal",
        "endpoints_minimal": [
            {
                "operationId": "samples_list",
                "path": "/nextseek_api/samples/",
                "method": "GET",
                "description": "List samples",
                "tags": ["samples"],
            },
            {
                "operationId": "samples_retrieve",
                "path": "/nextseek_api/samples/{uid}/",
                "method": "GET",
                "description": "Retrieve a sample by UID",
                "tags": ["samples"],
            },
        ],
    }


def _full_retrieve_payload() -> dict[str, Any]:
    return {
        "session_id": "sid-abc",
        "mode": "full",
        "endpoints_full": [
            {
                "operationId": "samples_retrieve",
                "path": "/nextseek_api/samples/{uid}/",
                "method": "GET",
                "description": "Retrieve a sample by UID",
                "tags": ["samples"],
                "parameters": {"uid": {"in": "path", "required": True, "type": "string"}},
                "request_schema": {},
                "response_schema": {"type": "object"},
                "examples": ["GET /nextseek_api/samples/A1/"],
                "relevance_score": 0.91,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test 1: ingest saves session to disk
# ---------------------------------------------------------------------------


def test_ingest_saves_session_to_disk(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """After ingest(), session.json must exist on disk with the CL-4 shape:
    session_id, expires_at, base_url, env_tag, schema_url."""
    mock_http_client.post.return_value = _ingest_payload("sid-xyz", future_iso, num_endpoints=137)

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    resp = rag.ingest()

    # Return value
    assert isinstance(resp, IngestResponse)
    assert resp.session_id == "sid-xyz"
    assert resp.num_endpoints == 137

    # On-disk state — CL-4 shape
    session_path = tmp_path / "dev" / "session.json"
    assert session_path.exists(), "ingest must persist session.json to disk"

    data = json.loads(session_path.read_text())
    assert data["session_id"] == "sid-xyz"
    assert data["schema_url"] == fake_schema_url
    assert data["env_tag"] == "dev", "CL-4: field is env_tag, not env"
    assert data["base_url"] == fake_base_url, "CL-4: base_url is required in session.json"
    # expires_at must round-trip as ISO-8601
    assert "expires_at" in data
    datetime.fromisoformat(data["expires_at"])  # should not raise

    # Round-trip via SessionState (CL-4 invariant)
    state = SessionState.model_validate(data)
    assert state.session_id == "sid-xyz"
    assert state.env_tag == "dev"
    assert state.base_url == fake_base_url

    # HTTP call
    mock_http_client.post.assert_called_once_with(
        "schema_rag/ingest/",
        json={"schema_url": fake_schema_url, "ttl_minutes": 30},
    )


# ---------------------------------------------------------------------------
# Test 2: retrieve minimal parses endpoints_minimal field
# ---------------------------------------------------------------------------


def test_retrieve_minimal_parses_endpoints_minimal_field(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """mode='minimal' must read raw['endpoints_minimal'] and build MinimalEndpoint[]."""
    mock_http_client.post.return_value = _minimal_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    # Seed a valid session so retrieve() does not auto-ingest.
    rag._write_session("sid-abc", datetime.fromisoformat(future_iso), fake_schema_url)

    resp = rag.retrieve("find samples", mode="minimal", top_k=5)

    assert isinstance(resp, SchemaRAGResponse)
    assert resp.total_results == 2
    assert all(isinstance(ep, MinimalEndpoint) for ep in resp.endpoints)
    assert resp.endpoints[0].operation_id == "samples_list"
    assert resp.endpoints[1].operation_id == "samples_retrieve"

    # Payload check: mode + top_k propagated
    sent = mock_http_client.post.call_args
    assert sent.args[0] == "schema_rag/retrieve/"
    body = sent.kwargs["json"]
    assert body["mode"] == "minimal"
    assert body["top_k"] == 5
    assert body["session_id"] == "sid-abc"


# ---------------------------------------------------------------------------
# Test 3: retrieve full parses endpoints_full field
# ---------------------------------------------------------------------------


def test_retrieve_full_parses_endpoints_full_field(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """mode='full' must read raw['endpoints_full'] and build FullEndpoint[]."""
    mock_http_client.post.return_value = _full_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session("sid-abc", datetime.fromisoformat(future_iso), fake_schema_url)

    resp = rag.retrieve("retrieve sample", mode="full", top_k=3)

    assert resp.total_results == 1
    ep = resp.endpoints[0]
    assert isinstance(ep, FullEndpoint)
    assert ep.operation_id == "samples_retrieve"
    assert ep.parameters == {"uid": {"in": "path", "required": True, "type": "string"}}
    assert ep.relevance_score == pytest.approx(0.91)

    body = mock_http_client.post.call_args.kwargs["json"]
    assert body["mode"] == "full"
    assert body["top_k"] == 3


# ---------------------------------------------------------------------------
# Test 4: top_k = "ALL" string literal
# ---------------------------------------------------------------------------


def test_retrieve_top_k_all_string(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """top_k='ALL' must be sent verbatim as a string in the JSON payload."""
    mock_http_client.post.return_value = _minimal_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session("sid-abc", datetime.fromisoformat(future_iso), fake_schema_url)

    rag.retrieve("all endpoints", mode="minimal", top_k="ALL", min_score=0.0)

    body = mock_http_client.post.call_args.kwargs["json"]
    assert body["top_k"] == "ALL", "top_k must be the literal string 'ALL', not coerced"
    assert isinstance(body["top_k"], str)
    assert body["min_score"] == 0.0


# ---------------------------------------------------------------------------
# Test 5: auto-reingest on expired session
# ---------------------------------------------------------------------------


def test_auto_reingest_on_expired_session(
    tmp_path: Path,
    mock_http_client: MagicMock,
    past_iso: str,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """If session.json.expires_at is in the past, retrieve_with_auto_ingest must
    call ingest() first, then retrieve() with the new session_id. Exactly 2 HTTP calls."""
    # Pre-populate session.json using the CL-4 shape directly (not via _write_session)
    # to exercise the round-trip from disk through current_session_state().
    (tmp_path / "dev").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dev" / "session.json").write_text(json.dumps({
        "session_id": "sid-old",
        "expires_at": past_iso,
        "base_url": fake_base_url,
        "env_tag": "dev",
        "schema_url": fake_schema_url,
    }))

    # Side-effect sequence:
    #   1. POST ingest/ → ingest response (fresh session)
    #   2. POST retrieve/ → minimal payload
    mock_http_client.post.side_effect = [
        _ingest_payload("sid-new", future_iso, num_endpoints=200),
        _minimal_retrieve_payload(),
    ]

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    resp = rag.retrieve_with_auto_ingest("find samples", mode="minimal", top_k=5)

    assert resp.total_results == 2

    # Exactly 2 HTTP calls: ingest then retrieve — reingest must fire exactly once.
    assert mock_http_client.post.call_count == 2
    first_call, second_call = mock_http_client.post.call_args_list
    assert first_call.args[0] == "schema_rag/ingest/"
    assert second_call.args[0] == "schema_rag/retrieve/"
    assert second_call.kwargs["json"]["session_id"] == "sid-new"

    # session.json on disk must now hold the new session in CL-4 shape
    data = json.loads((tmp_path / "dev" / "session.json").read_text())
    assert data["session_id"] == "sid-new"
    assert data["env_tag"] == "dev"
    assert data["base_url"] == fake_base_url


# ---------------------------------------------------------------------------
# Test 6: auto-reingest on 401 from retrieve (once)
# ---------------------------------------------------------------------------


def test_auto_reingest_on_401_from_retrieve(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """Fresh session but server returns 401 on retrieve → reingest + retry exactly once.

    Mock raises auth error on the first retrieve attempt, succeeds on the second
    retrieve (after the implicit reingest in between). Total wire calls: 3
    (retrieve-401, ingest, retrieve-success) == 2 retrieve attempts plus 1 reingest.
    """
    auth_err = NextseekAuthError("session expired on server")

    # Sequence:
    #   1. POST retrieve/ → 401 (session valid locally but rejected server-side)
    #   2. POST ingest/   → fresh sid-new
    #   3. POST retrieve/ → success payload
    mock_http_client.post.side_effect = [
        auth_err,
        _ingest_payload("sid-new", future_iso, num_endpoints=55),
        _minimal_retrieve_payload(),
    ]

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    # Seed a still-valid session so the pre-check does NOT reingest.
    rag._write_session("sid-stale", datetime.fromisoformat(future_iso), fake_schema_url)

    resp = rag.retrieve_with_auto_ingest("find samples", mode="minimal", top_k=5)

    assert resp.total_results == 2
    # Exactly 2 retrieve attempts (1 failed + 1 succeeded) plus 1 reingest = 3 calls.
    assert mock_http_client.post.call_count == 3

    endpoints = [c.args[0] for c in mock_http_client.post.call_args_list]
    assert endpoints == [
        "schema_rag/retrieve/",
        "schema_rag/ingest/",
        "schema_rag/retrieve/",
    ]

    # Last retrieve must use the NEW session id
    last = mock_http_client.post.call_args_list[-1]
    assert last.kwargs["json"]["session_id"] == "sid-new"

    # Session file updated, still in CL-4 shape
    data = json.loads((tmp_path / "dev" / "session.json").read_text())
    assert data["session_id"] == "sid-new"
    assert data["env_tag"] == "dev"
    assert data["base_url"] == fake_base_url


# ---------------------------------------------------------------------------
# Test 7: auto-reingest failure raises original error (no infinite loop)
# ---------------------------------------------------------------------------


def test_auto_reingest_failure_raises(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """If the reingest itself fails, the client must raise the ORIGINAL 401 — no infinite loop.

    Sequence (exactly 2 HTTP calls):
      1. POST retrieve/ → 401 (the original auth error)
      2. POST ingest/   → raises (reingest itself fails)
      → client re-raises the original 401, never attempts a third call.
    """
    original_err = NextseekAuthError("401 on retrieve")
    reingest_err = NextseekAuthError("401 on reingest")

    mock_http_client.post.side_effect = [
        original_err,
        reingest_err,
    ]

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    # Seed a still-valid session so the pre-check does NOT reingest.
    rag._write_session("sid-stale", datetime.fromisoformat(future_iso), fake_schema_url)

    with pytest.raises(NextseekAuthError):
        rag.retrieve_with_auto_ingest("find samples", mode="minimal", top_k=5)

    # Exactly 2 HTTP calls: the first retrieve (401) and the reingest (also fails).
    # No 3rd call is attempted because reingest raised before any retry retrieve.
    assert mock_http_client.post.call_count == 2
    endpoints = [c.args[0] for c in mock_http_client.post.call_args_list]
    assert endpoints == [
        "schema_rag/retrieve/",
        "schema_rag/ingest/",
    ]


# ---------------------------------------------------------------------------
# Test 8: env-scoped cache directories
# ---------------------------------------------------------------------------


def test_env_scoped_cache_directories(
    tmp_path: Path,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """Dev and prod sessions must land in separate subdirectories (tmp_path/dev vs tmp_path/prod)."""
    dev_http = MagicMock(name="DevClient")
    dev_http.post.return_value = _ingest_payload("sid-dev", future_iso)

    prod_http = MagicMock(name="ProdClient")
    prod_http.post.return_value = _ingest_payload("sid-prod", future_iso)

    prod_base_url = "https://nextseek.mit.edu/nextseek_api"

    dev_rag = SchemaRAGClient(
        http_client=dev_http,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    prod_rag = SchemaRAGClient(
        http_client=prod_http,
        env_tag="prod",
        base_url=prod_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    dev_rag.ingest()
    prod_rag.ingest()

    dev_session = tmp_path / "dev" / "session.json"
    prod_session = tmp_path / "prod" / "session.json"

    assert dev_session.exists()
    assert prod_session.exists()

    dev_data = json.loads(dev_session.read_text())
    prod_data = json.loads(prod_session.read_text())

    assert dev_data["session_id"] == "sid-dev"
    assert dev_data["env_tag"] == "dev"
    assert dev_data["base_url"] == fake_base_url
    assert prod_data["session_id"] == "sid-prod"
    assert prod_data["env_tag"] == "prod"
    assert prod_data["base_url"] == prod_base_url

    # Cross-contamination check: dev file must NOT contain prod data
    assert "sid-prod" not in dev_session.read_text()
    assert "sid-dev" not in prod_session.read_text()


# ---------------------------------------------------------------------------
# Test 9: current_session_state returns a SessionState pydantic model
# ---------------------------------------------------------------------------


def test_current_session_state_returns_pydantic_model(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """After ingest, current_session_state() must return a SessionState instance
    with the correct fields (CL-3 API lock)."""
    mock_http_client.post.return_value = _ingest_payload("sid-curr", future_iso)

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag.ingest()

    state = rag.current_session_state()
    assert state is not None
    assert isinstance(state, SessionState)
    assert state.session_id == "sid-curr"
    assert state.env_tag == "dev"
    assert state.base_url == fake_base_url
    assert state.schema_url == fake_schema_url
    # expires_at is a datetime after model validation
    assert isinstance(state.expires_at, datetime)


# ---------------------------------------------------------------------------
# Test 10: current_session_state returns None when session.json is missing
# ---------------------------------------------------------------------------


def test_current_session_state_returns_none_when_missing(
    tmp_path: Path,
    mock_http_client: MagicMock,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """A fresh cache dir with no session.json → current_session_state() returns None."""
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    # No ingest called, no session.json on disk.
    assert rag.current_session_state() is None


# ---------------------------------------------------------------------------
# Test 11: XDG_CACHE_HOME is honored when cache_base_dir is None (CL-7)
# ---------------------------------------------------------------------------


def test_xdg_cache_home_honored(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With XDG_CACHE_HOME=tmp_path and cache_base_dir=None, session.json must
    land at tmp_path/nextseek-api/dev/session.json (via lib.cache_paths)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    mock_http_client.post.return_value = _ingest_payload("sid-xdg", future_iso)

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=None,  # ← triggers resolve_plugin_cache_base()
    )
    rag.ingest()

    expected = tmp_path / "nextseek-api" / "v2" / "dev" / "session.json"
    assert expected.exists(), f"expected session.json at {expected}, did not find it"

    data = json.loads(expected.read_text())
    assert data["session_id"] == "sid-xdg"
    assert data["env_tag"] == "dev"
    assert data["base_url"] == fake_base_url


# ---------------------------------------------------------------------------
# Coverage: context manager protocol
# ---------------------------------------------------------------------------


def test_context_manager_protocol(
    tmp_path: Path,
    mock_http_client: MagicMock,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """SchemaRAGClient supports the with-statement (CL-3)."""
    with SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    ) as rag:
        assert isinstance(rag, SchemaRAGClient)


# ---------------------------------------------------------------------------
# Coverage: invalid env_tag
# ---------------------------------------------------------------------------


def test_invalid_env_tag_raises_value_error(
    mock_http_client: MagicMock,
    tmp_path: Path,
    fake_base_url: str,
) -> None:
    """env_tag must be 'dev' or 'prod'."""
    with pytest.raises(ValueError, match="env_tag must be"):
        SchemaRAGClient(
            http_client=mock_http_client,
            env_tag="staging",  # type: ignore[arg-type]
            base_url=fake_base_url,
            cache_base_dir=tmp_path,
        )


# ---------------------------------------------------------------------------
# Coverage: retrieve with filter_by, filter_terms, schema_url
# ---------------------------------------------------------------------------


def test_retrieve_passes_filter_and_schema_url(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """filter_by, filter_terms, and schema_url must be forwarded to the payload."""
    mock_http_client.post.return_value = _minimal_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session("sid-abc", datetime.fromisoformat(future_iso), fake_schema_url)

    rag.retrieve(
        "find samples",
        mode="minimal",
        filter_by="tags",
        filter_terms=["samples"],
        schema_url="https://custom-schema.example.com/schema.yaml",
    )

    body = mock_http_client.post.call_args.kwargs["json"]
    assert body["filter_by"] == "tags"
    assert body["filter_terms"] == ["samples"]
    assert body["schema_url"] == "https://custom-schema.example.com/schema.yaml"


# ---------------------------------------------------------------------------
# Coverage: corrupted session.json
# ---------------------------------------------------------------------------


def test_current_session_state_returns_none_on_corrupted_json(
    tmp_path: Path,
    mock_http_client: MagicMock,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """Corrupted session.json must return None, not raise."""
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    # Write invalid JSON
    (tmp_path / "dev" / "session.json").write_text("not valid json{{{")
    assert rag.current_session_state() is None


def test_current_session_state_returns_none_on_invalid_schema(
    tmp_path: Path,
    mock_http_client: MagicMock,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """Valid JSON but invalid SessionState shape must return None."""
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    # Write valid JSON but missing required fields
    (tmp_path / "dev" / "session.json").write_text(json.dumps({"foo": "bar"}))
    assert rag.current_session_state() is None


# ---------------------------------------------------------------------------
# Coverage: _session_json_path, _load_cached_session, clear_session_cache
# ---------------------------------------------------------------------------


def test_session_json_path_returns_correct_path(
    tmp_path: Path,
    mock_http_client: MagicMock,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """_session_json_path must point to {cache_dir}/{env}/session.json."""
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    assert rag._session_json_path() == tmp_path / "dev" / "session.json"


def test_load_cached_session_delegates_to_current_session_state(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """_load_cached_session is an alias for current_session_state."""
    mock_http_client.post.return_value = _ingest_payload("sid-lcs", future_iso)

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag.ingest()

    state = rag._load_cached_session()
    assert state is not None
    assert state.session_id == "sid-lcs"


def test_clear_session_cache_removes_file(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """clear_session_cache must delete session.json; idempotent on missing file."""
    mock_http_client.post.return_value = _ingest_payload("sid-clr", future_iso)

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag.ingest()
    assert (tmp_path / "dev" / "session.json").exists()

    rag.clear_session_cache()
    assert not (tmp_path / "dev" / "session.json").exists()

    # Idempotent: calling again should not raise
    rag.clear_session_cache()


# ---------------------------------------------------------------------------
# DD-15 (task-02 / issue #17): retrieve() raises SessionExpiredError on expiry
# ---------------------------------------------------------------------------


def test_retrieve_raises_session_expired_on_expired_cache(
    tmp_path: Path,
    mock_http_client: MagicMock,
    past_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """retrieve() must raise SessionExpiredError BEFORE any HTTP call when
    the cached session.json is past its TTL and no explicit session_id
    was passed."""
    (tmp_path / "dev").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dev" / "session.json").write_text(json.dumps({
        "session_id": "sid-stale",
        "expires_at": past_iso,
        "base_url": fake_base_url,
        "env_tag": "dev",
        "schema_url": fake_schema_url,
    }))

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    with pytest.raises(SessionExpiredError, match="session expired"):
        rag.retrieve("anything", mode="minimal", top_k=5)

    # Zero HTTP calls — the error must fire before the wire.
    mock_http_client.post.assert_not_called()


def test_retrieve_with_explicit_session_id_skips_expiry_check(
    tmp_path: Path,
    mock_http_client: MagicMock,
    past_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """If the caller passes session_id=..., the cached-expiry check is
    bypassed (caller is explicitly overriding). The HTTP call proceeds."""
    (tmp_path / "dev").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dev" / "session.json").write_text(json.dumps({
        "session_id": "sid-stale",
        "expires_at": past_iso,
        "base_url": fake_base_url,
        "env_tag": "dev",
        "schema_url": fake_schema_url,
    }))
    mock_http_client.post.return_value = _minimal_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )

    resp = rag.retrieve(
        "anything", mode="minimal", top_k=5, session_id="sid-override"
    )
    assert resp.total_results == 2
    body = mock_http_client.post.call_args.kwargs["json"]
    assert body["session_id"] == "sid-override"


def test_session_expired_error_default_message() -> None:
    """Human-friendly default message is contract-locked (DD-15)."""
    err = SessionExpiredError()
    assert "session expired" in str(err)
    assert "nextseek-init" in str(err)


def test_session_expired_error_is_nextseek_client_error() -> None:
    """Must subclass NextseekClientError for broad except blocks."""
    from lib.nextseek_client import NextseekClientError

    err = SessionExpiredError()
    assert isinstance(err, NextseekClientError)


# ---------------------------------------------------------------------------
# DD-5: snake_case harmonization — retrieve() returns models whose
# model_dump() emits snake_case keys (operation_id, endpoint).
# ---------------------------------------------------------------------------


def test_retrieve_minimal_endpoints_dump_snake_case(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    """DD-5: dumping retrieved endpoints yields snake_case keys only."""
    mock_http_client.post.return_value = _minimal_retrieve_payload()

    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    resp = rag.retrieve(query="samples", mode="minimal")
    dumped = [ep.model_dump(by_alias=False) for ep in resp.endpoints]
    assert len(dumped) == 2
    for ep in dumped:
        assert "operation_id" in ep
        assert "endpoint" in ep
        assert "operationId" not in ep
        assert "path" not in ep


# ---------------------------------------------------------------------------
# task-06b additions: retrieve_full / retrieve_full_by_query
# ---------------------------------------------------------------------------


def test_retrieve_full_returns_matching_endpoint(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    mock_http_client.post.return_value = _full_retrieve_payload()
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session(
        "sid-abc", datetime.fromisoformat(future_iso), fake_schema_url
    )

    ep = rag.retrieve_full("samples_retrieve")
    assert isinstance(ep, FullEndpoint)
    assert ep.operation_id == "samples_retrieve"


def test_retrieve_full_raises_lookup_error_on_mismatch(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    mock_http_client.post.return_value = _full_retrieve_payload()
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session(
        "sid-abc", datetime.fromisoformat(future_iso), fake_schema_url
    )
    with pytest.raises(LookupError):
        rag.retrieve_full("nonexistent_op")


def test_retrieve_full_by_query_returns_top_hit(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    mock_http_client.post.return_value = _full_retrieve_payload()
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session(
        "sid-abc", datetime.fromisoformat(future_iso), fake_schema_url
    )

    ep = rag.retrieve_full_by_query("find a sample")
    assert isinstance(ep, FullEndpoint)
    assert ep.operation_id == "samples_retrieve"


def test_retrieve_full_by_query_raises_on_no_hits(
    tmp_path: Path,
    mock_http_client: MagicMock,
    future_iso: str,
    fake_schema_url: str,
    fake_base_url: str,
) -> None:
    mock_http_client.post.return_value = {
        "session_id": "sid-abc",
        "mode": "full",
        "endpoints_full": [],
    }
    rag = SchemaRAGClient(
        http_client=mock_http_client,
        env_tag="dev",
        base_url=fake_base_url,
        default_schema_url=fake_schema_url,
        cache_base_dir=tmp_path,
    )
    rag._write_session(
        "sid-abc", datetime.fromisoformat(future_iso), fake_schema_url
    )
    with pytest.raises(LookupError):
        rag.retrieve_full_by_query("nothing matches")
