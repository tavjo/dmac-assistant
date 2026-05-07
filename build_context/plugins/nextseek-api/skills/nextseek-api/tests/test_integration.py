"""End-to-end integration tests for the nextseek-api plugin.

Exercises the exact sequence of CLI invocations that Claude Code will issue in a
real /nextseek-api session. All HTTP calls are intercepted by httpx.MockTransport;
no live NExtSEEK API calls are made.

Scenarios:
  1. test_full_bootstrap_flow                            — init_session writes cache
  2. test_full_query_flow_get                            — bootstrap → get → validate → exec
  3. test_session_expiry_triggers_auto_reingest          — expired session.json → silent reingest
  4. test_write_blocked_at_layer_2_without_confirmed_write — POST /samples/upload/ blocked pre-HTTP
  5. test_schemarag_post_passes_through_safety           — POST schema_rag/retrieve/ allowed
  6. test_path_param_interpolation_end_to_end            — {uid} rendered into URL
  7. test_dev_and_prod_caches_isolated                   — env-scoped cache dirs independent
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import httpx
import pytest

# --- Import path setup ---
# conftest.py already puts scripts/ on sys.path via its _SCRIPTS_DIR insert.
# Import the CLI modules by bare name.
import execute_request
import fetch_spec
import init_session
import validate_request


# =============================================================================
# Shared fixtures
# =============================================================================

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture
def fake_plugin_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Simulate CLAUDE_PLUGIN_ROOT for bin/ shim resolution."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT))
    return PLUGIN_ROOT


@pytest.fixture
def fake_cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all cache writes under tmp_path/cache/nextseek-api/."""
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache / "nextseek-api" / "v2"


@pytest.fixture
def fake_env_file(tmp_path: Path) -> Path:
    """Create a .env with canonical variable names for the env_loader."""
    env_path = tmp_path / "fake.env"
    env_path.write_text(
        "NEXTSEEK_BASE_URL=https://nextseek-dev.mit.edu\n"
        "SEEK_USER=alice\n"
        "SEEK_PASSWORD=hunter2\n"
    )
    return env_path


# =============================================================================
# Mock response fixtures — shapes match real NExtSEEK SchemaRAG server
# =============================================================================

INGEST_RESPONSE: dict[str, Any] = {
    "session_id": "sess-integ-001",
    "schema_url": "https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml",
    "ttl_minutes": 30,
    "expires_at": "2099-12-31T23:59:59Z",
    "num_endpoints": 2,
}

MINIMAL_RESPONSE: dict[str, Any] = {
    "session_id": "sess-integ-001",
    "expires_at": "2099-12-31T23:59:59Z",
    "mode": "minimal",
    "endpoints_minimal": [
        {
            "operationId": "samples_retrieve",
            "method": "GET",
            "path": "/nextseek_api/samples/{uid}/",
            "summary": "Retrieve a sample by UID",
            "tags": ["samples"],
            "relevance_score": 0.95,
        },
        {
            "operationId": "samples_upload",
            "method": "POST",
            "path": "/nextseek_api/samples/upload/",
            "summary": "Upload new samples",
            "tags": ["samples", "write"],
            "relevance_score": 0.42,
        },
    ],
}

FULL_RESPONSE_GET: dict[str, Any] = {
    "session_id": "sess-integ-001",
    "expires_at": "2099-12-31T23:59:59Z",
    "mode": "full",
    "endpoints_full": [
        {
            "operationId": "samples_retrieve",
            "method": "GET",
            "path": "/nextseek_api/samples/{uid}/",
            "summary": "Retrieve a sample by UID",
            "description": "Fetch a single sample record by its UID.",
            "tags": ["samples"],
            "parameters": [
                {
                    "name": "uid",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "request_schema": {},
            "response_schema": {"type": "object"},
            "relevance_score": 0.95,
        }
    ],
}

FULL_RESPONSE_POST_UPLOAD: dict[str, Any] = {
    "session_id": "sess-integ-001",
    "expires_at": "2099-12-31T23:59:59Z",
    "mode": "full",
    "endpoints_full": [
        {
            "operationId": "samples_upload",
            "method": "POST",
            "path": "/nextseek_api/samples/upload/",
            "summary": "Upload new samples",
            "description": "Bulk upload samples.",
            "tags": ["samples", "write"],
            "parameters": [],
            "request_schema": {
                "type": "object",
                "required": ["samples"],
                "properties": {"samples": {"type": "array"}},
            },
            "response_schema": {"type": "object"},
            "relevance_score": 0.42,
        }
    ],
}

SAMPLE_GET_RESPONSE: dict[str, Any] = {
    "uid": "A1",
    "name": "Sample A1",
    "project_id": "P001",
    "status": "active",
}


# =============================================================================
# MockTransport handler factory
# =============================================================================

class _HandlerCounter:
    """Records every request the handler sees; lets tests assert call counts."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def record(self, request: httpx.Request) -> None:
        self.calls.append((request.method, request.url.path))

    @property
    def count(self) -> int:
        return len(self.calls)


def _make_handler(
    counter: _HandlerCounter,
    *,
    get_response: dict[str, Any] | None = None,
    full_response: dict[str, Any] | None = None,
    minimal_response: dict[str, Any] | None = None,
    ingest_response: dict[str, Any] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that routes by method + path."""

    def handler(request: httpx.Request) -> httpx.Response:
        counter.record(request)
        path = request.url.path
        method = request.method

        # Task-01 preflight probe: init_session issues GET schema/?format=yaml
        # against the base URL before ingest. Return 200 so preflight passes.
        # (Task 5R: previous default schema_rag/schema/ did not exist on the
        # live server — default was corrected to schema/?format=yaml.)
        if method == "GET" and path.rstrip("/").endswith("/schema"):
            return httpx.Response(200, json={"schema": "ok"})

        if method == "POST" and "schema_rag/ingest" in path:
            return httpx.Response(200, json=ingest_response or INGEST_RESPONSE)

        if method == "POST" and "schema_rag/retrieve" in path:
            try:
                body = json.loads(request.content.decode() or "{}")
            except Exception:
                body = {}
            mode = body.get("mode", "minimal")
            if mode == "full":
                return httpx.Response(200, json=full_response or FULL_RESPONSE_GET)
            return httpx.Response(200, json=minimal_response or MINIMAL_RESPONSE)

        # Task-07: entity tree fetch is part of bootstrap (non-fatal).
        if method == "GET" and "entity_tree/nodes" in path:
            return httpx.Response(
                200,
                json={
                    "count": 0,
                    "next": None,
                    "results": {"total": 0, "nodes": []},
                },
            )
        if method == "GET" and "entity_tree/edge_attributes" in path:
            return httpx.Response(
                200,
                json={
                    "count": 0,
                    "next": None,
                    "results": {"total": 0, "edges": []},
                },
            )

        if method == "GET" and "samples/" in path:
            return httpx.Response(200, json=get_response or SAMPLE_GET_RESPONSE)

        return httpx.Response(404, json={"error": f"unmocked {method} {path}"})

    return handler


@pytest.fixture
def mock_transport_factory():
    """Yield a factory that produces (handler, counter) pairs per scenario."""

    def _factory(**kwargs: Any) -> tuple[Callable[..., httpx.Response], _HandlerCounter]:
        counter = _HandlerCounter()
        handler = _make_handler(counter, **kwargs)
        return handler, counter

    return _factory


@pytest.fixture
def patch_httpx_client(monkeypatch: pytest.MonkeyPatch):
    """Monkeypatch httpx.Client to inject a MockTransport for any plugin script."""

    def _install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        real_client = httpx.Client

        def _patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", _patched_client)

    return _install


# =============================================================================
# Helper to seed caches
# =============================================================================

def _seed_session(cache_root: Path, env: str, *, expired: bool = False) -> None:
    """Write a session.json to the env-scoped cache dir."""
    dev_cache = cache_root / env
    dev_cache.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": "sess-integ-001",
        "expires_at": "1970-01-01T00:00:00Z" if expired else "2099-12-31T23:59:59Z",
        "base_url": "https://nextseek-dev.mit.edu",
        "env_tag": env,
        "schema_url": "https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml",
    }
    (dev_cache / "session.json").write_text(json.dumps(session))


def _seed_minimal_cache(cache_root: Path, env: str) -> None:
    """Write a minimal endpoints cache."""
    dev_cache = cache_root / env
    dev_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "env_tag": env,
        "session_id": "sess-integ-001",
        "expires_at": "2099-12-31T23:59:59Z",
        "base_url": "https://nextseek-dev.mit.edu",
        "fetched_at": "2099-01-01T00:00:00Z",
        "endpoints": [
            ep for ep in MINIMAL_RESPONSE["endpoints_minimal"]
        ],
    }
    (dev_cache / "endpoints_minimal.json").write_text(json.dumps(payload))


def _seed_full_endpoint(cache_root: Path, env: str, op_id: str, data: dict) -> None:
    """Write a cached full endpoint spec."""
    full_dir = cache_root / env / "endpoints_full"
    full_dir.mkdir(parents=True, exist_ok=True)
    (full_dir / f"{op_id}.json").write_text(json.dumps(data))


# =============================================================================
# Test 1 — full bootstrap flow
# =============================================================================
def test_full_bootstrap_flow(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
) -> None:
    handler, counter = mock_transport_factory()
    patch_httpx_client(handler)

    argv = [
        "init_session.py", "--env", "dev", "--env-file", str(fake_env_file),
        "--skip-preflight",
    ]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()

    assert exit_code == 0

    # Verify endpoints_minimal.json was written.
    cache_file = fake_cache_root / "dev" / "endpoints_minimal.json"
    assert cache_file.exists()

    payload = json.loads(cache_file.read_text())
    assert payload["env_tag"] == "dev"
    assert len(payload["endpoints"]) == 2
    assert payload["endpoints"][0]["operation_id"] == "samples_retrieve"

    # Verify session.json was written.
    session_file = fake_cache_root / "dev" / "session.json"
    assert session_file.exists()
    assert "sess-integ-001" in session_file.read_text()

    # Bootstrap: ingest + retrieve(minimal) + entity_tree nodes + edges = 4 calls.
    assert counter.count == 4
    assert counter.calls[0][0] == "POST"
    assert "schema_rag/ingest" in counter.calls[0][1]
    assert counter.calls[1][0] == "POST"
    assert "schema_rag/retrieve" in counter.calls[1][1]
    # Task-07: entity tree fetch follows schema ingest.
    assert counter.calls[2][0] == "GET"
    assert "entity_tree/nodes" in counter.calls[2][1]
    assert counter.calls[3][0] == "GET"
    assert "entity_tree/edge_attributes" in counter.calls[3][1]
    # Verify the entity tree cache was written.
    tree_file = fake_cache_root / "dev" / "entity_tree.json"
    assert tree_file.exists()
    tree_data = json.loads(tree_file.read_text())
    assert "nodes" in tree_data and "edges" in tree_data
    assert tree_data["session_id"] == "sess-integ-001"


# =============================================================================
# Test 2 — full query flow (GET)
# =============================================================================
def test_full_query_flow_get(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
    tmp_path: Path,
) -> None:
    """Full round-trip: bootstrap → read cache → get spec → validate → exec."""
    handler, counter = mock_transport_factory(
        full_response=FULL_RESPONSE_GET,
        get_response=SAMPLE_GET_RESPONSE,
    )
    patch_httpx_client(handler)

    # --- Step 1: bootstrap ---
    with patch.object(
        sys, "argv",
        [
            "init_session.py", "--env", "dev", "--env-file", str(fake_env_file),
            "--skip-preflight",
        ],
    ):
        assert init_session.main() == 0

    # --- Step 2: get full spec ---
    with patch.object(
        sys, "argv",
        [
            "fetch_spec.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--operation-id", "samples_retrieve",
        ],
    ):
        assert fetch_spec.main() == 0

    full_cache = (
        fake_cache_root / "dev" / "endpoints_full" / "samples_retrieve.json"
    )
    assert full_cache.exists()
    full_payload = json.loads(full_cache.read_text())
    # task-06b: cache is now wrapped as {"session_id": ..., "spec": {...}}.
    assert "session_id" in full_payload
    assert full_payload["spec"]["operation_id"] == "samples_retrieve"
    assert full_payload["spec"]["method"] == "GET"

    # --- Step 3: construct RequestSpec & validate ---
    spec = {
        "operation_id": "samples_retrieve",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "A1"},
        "query_params": {},
        "headers": {},
        "request_body": None,
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    with patch.object(
        sys, "argv",
        [
            "validate_request.py",
            "--env", "dev",
            "--file", str(spec_file),
        ],
    ):
        assert validate_request.main() == 0

    # --- Step 4: execute ---
    with patch.object(
        sys, "argv",
        [
            "execute_request.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--file", str(spec_file),
        ],
    ):
        exit_code = execute_request.main()

    assert exit_code == 0

    # The GET must have hit /samples/A1/ (path interpolated by httpx base_url join).
    # Filter out Task-07 entity tree GETs (part of bootstrap, not query flow).
    get_calls = [
        c for c in counter.calls
        if c[0] == "GET" and "entity_tree" not in c[1]
    ]
    assert len(get_calls) == 1
    assert get_calls[0][1].endswith("/samples/A1/")


# =============================================================================
# Test 3 — session expiry triggers auto-reingest
# =============================================================================
def test_session_expiry_triggers_auto_reingest(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
) -> None:
    # Pre-populate an expired session.json.
    _seed_session(fake_cache_root, "dev", expired=True)
    _seed_minimal_cache(fake_cache_root, "dev")

    handler, counter = mock_transport_factory(full_response=FULL_RESPONSE_GET)
    patch_httpx_client(handler)

    with patch.object(
        sys, "argv",
        [
            "fetch_spec.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--operation-id", "samples_retrieve",
            "--no-cache",
        ],
    ):
        exit_code = fetch_spec.main()

    assert exit_code == 0

    # Must have seen an ingest (session was expired) followed by a retrieve(full).
    paths = [c[1] for c in counter.calls]
    assert any("schema_rag/ingest" in p for p in paths), (
        f"expected a reingest call; saw {counter.calls}"
    )
    assert any("schema_rag/retrieve" in p for p in paths)

    # session.json updated to the fresh session_id.
    dev_cache = fake_cache_root / "dev"
    fresh_session = json.loads((dev_cache / "session.json").read_text())
    assert fresh_session["session_id"] == "sess-integ-001"
    assert fresh_session["expires_at"] != "1970-01-01T00:00:00Z"


# =============================================================================
# Test 4 — Layer 2 blocks write without --confirmed-write
# =============================================================================
def test_write_blocked_at_layer_2_without_confirmed_write(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler, counter = mock_transport_factory(
        full_response=FULL_RESPONSE_POST_UPLOAD,
    )
    patch_httpx_client(handler)

    # Seed caches so we don't have to bootstrap.
    _seed_session(fake_cache_root, "dev")
    _seed_full_endpoint(
        fake_cache_root, "dev", "samples_upload",
        FULL_RESPONSE_POST_UPLOAD["endpoints_full"][0],
    )
    _seed_minimal_cache(fake_cache_root, "dev")

    spec = {
        "operation_id": "samples_upload",
        "method": "POST",
        "endpoint": "/nextseek_api/samples/upload/",
        "path_params": {},
        "query_params": {},
        "headers": {},
        "request_body": {"samples": [{"uid": "A1"}]},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    # Run WITHOUT --confirmed-write.
    with patch.object(
        sys, "argv",
        [
            "execute_request.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--file", str(spec_file),
        ],
    ):
        exit_code = execute_request.main()

    captured = capsys.readouterr()
    assert exit_code != 0, "execute_request.py must refuse writes without --confirmed-write"
    assert "SafetyPolicyBlocked" in captured.err, (
        f"expected SafetyPolicyBlocked in stderr; got: {captured.err!r}"
    )

    # CRITICAL: the HTTP layer must never have been reached.
    assert counter.count == 0, (
        f"Layer 2 must block BEFORE any HTTP call; handler saw {counter.calls}"
    )


# =============================================================================
# Test 5 — schema_rag POST is allowed without --confirmed-write
# =============================================================================
def test_schemarag_post_passes_through_safety(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
    tmp_path: Path,
) -> None:
    handler, counter = mock_transport_factory()
    patch_httpx_client(handler)

    # Seed session + full spec for schema_rag_retrieve.
    _seed_session(fake_cache_root, "dev")
    schema_rag_endpoint = {
        "operationId": "schema_rag_retrieve",
        "method": "POST",
        "path": "/nextseek_api/schema_rag/retrieve/",
        "summary": "Retrieve endpoints via SchemaRAG",
        "description": "Read-only SchemaRAG retrieval.",
        "tags": ["schema_rag"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        "response_schema": {"type": "object"},
        "relevance_score": 1.0,
    }
    _seed_full_endpoint(
        fake_cache_root, "dev", "schema_rag_retrieve", schema_rag_endpoint,
    )
    _seed_minimal_cache(fake_cache_root, "dev")

    spec = {
        "operation_id": "schema_rag_retrieve",
        "method": "POST",
        "endpoint": "/nextseek_api/schema_rag/retrieve/",
        "path_params": {},
        "query_params": {},
        "headers": {},
        "request_body": {"query": "samples", "mode": "minimal", "top_k": 5},
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    with patch.object(
        sys, "argv",
        [
            "execute_request.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--file", str(spec_file),
        ],
    ):
        exit_code = execute_request.main()

    assert exit_code == 0, "POST to schema_rag/retrieve/ must be allowed without --confirmed-write"
    # The mock handler saw a POST to schema_rag/retrieve/.
    retrieve_calls = [
        c for c in counter.calls
        if c[0] == "POST" and "schema_rag/retrieve" in c[1]
    ]
    assert len(retrieve_calls) >= 1


# =============================================================================
# Test 6 — path param interpolation end-to-end
# =============================================================================
def test_path_param_interpolation_end_to_end(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
    tmp_path: Path,
) -> None:
    handler, counter = mock_transport_factory(
        full_response=FULL_RESPONSE_GET,
        get_response={"uid": "A1", "found": True},
    )
    patch_httpx_client(handler)

    # Seed caches.
    _seed_session(fake_cache_root, "dev")
    _seed_full_endpoint(
        fake_cache_root, "dev", "samples_retrieve",
        FULL_RESPONSE_GET["endpoints_full"][0],
    )
    _seed_minimal_cache(fake_cache_root, "dev")

    spec = {
        "operation_id": "samples_retrieve",
        "method": "GET",
        "endpoint": "/nextseek_api/samples/{uid}/",
        "path_params": {"uid": "A1"},
        "query_params": {},
        "headers": {},
        "request_body": None,
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    with patch.object(
        sys, "argv",
        [
            "execute_request.py",
            "--env", "dev",
            "--env-file", str(fake_env_file),
            "--file", str(spec_file),
        ],
    ):
        exit_code = execute_request.main()

    assert exit_code == 0
    # Filter out Task-07 entity tree GETs (part of bootstrap, not query flow).
    get_calls = [
        c for c in counter.calls
        if c[0] == "GET" and "entity_tree" not in c[1]
    ]
    assert len(get_calls) == 1
    # The path should contain /samples/A1/ with no unresolved braces.
    assert "/samples/A1/" in get_calls[0][1], (
        f"expected interpolated path with /samples/A1/; got {get_calls[0][1]}"
    )


# =============================================================================
# Test 7 — dev and prod caches isolated
# =============================================================================
def test_dev_and_prod_caches_isolated(
    fake_plugin_root: Path,
    fake_cache_root: Path,
    fake_env_file: Path,
    mock_transport_factory,
    patch_httpx_client,
) -> None:
    handler, counter = mock_transport_factory()
    patch_httpx_client(handler)

    # Bootstrap against dev.
    with patch.object(
        sys, "argv",
        ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)],
    ):
        assert init_session.main() == 0

    # Bootstrap against prod. fake_env_file sets NEXTSEEK_BASE_URL to the dev
    # host; selecting --env prod therefore trips detect_env_mismatch ->
    # "dev-prod". --assume-yes bypasses the interactive confirm for tests.
    with patch.object(
        sys, "argv",
        [
            "init_session.py",
            "--env", "prod",
            "--env-file", str(fake_env_file),
            "--assume-yes",
        ],
    ):
        assert init_session.main() == 0

    dev_session = fake_cache_root / "dev" / "session.json"
    prod_session = fake_cache_root / "prod" / "session.json"
    dev_minimal = fake_cache_root / "dev" / "endpoints_minimal.json"
    prod_minimal = fake_cache_root / "prod" / "endpoints_minimal.json"

    assert dev_session.exists()
    assert prod_session.exists()
    assert dev_minimal.exists()
    assert prod_minimal.exists()
    assert dev_session.parent != prod_session.parent

    dev_payload = json.loads(dev_minimal.read_text())
    prod_payload = json.loads(prod_minimal.read_text())
    assert dev_payload["env_tag"] == "dev"
    assert prod_payload["env_tag"] == "prod"
