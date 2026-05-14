"""Tests for scripts/fetch_spec.py — full-spec fetcher.

Covers task-06b additions (DD-6 + DD-7):
  * ``build_request_spec_template`` produces prefilled RequestSpec skeletons.
  * ``main`` emits both ``spec`` and ``request_spec_template`` blocks.
  * ``--print-example`` prints only the template.
  * Lazy per-op cache under ``endpoints_full/{op_id}.json`` with session-id
    invalidation; legacy ``--query`` path still works.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# CL-1: conftest.py from task-01 puts `scripts/` on sys.path so `lib.*` and
# top-level script modules are importable. No sys.path hacks here.
import fetch_spec  # noqa: E402
from lib.cache_paths import resolve_endpoint_full_path  # noqa: E402
from lib.models import FullEndpoint, SchemaRAGResponse  # noqa: E402
from lib.nextseek_client import NextseekConfig  # noqa: E402


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
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    env_dir = cache / "nextseek-api" / "v2" / "dev"
    (env_dir / "endpoints_full").mkdir(parents=True, exist_ok=True)
    return env_dir


@pytest.fixture
def fake_config() -> NextseekConfig:
    return NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="alice",
        password="hunter2",
    )


def _make_full_endpoint(
    op_id: str,
    score: float = 0.9,
    method: str = "GET",
    path: str = "/nextseek_api/samples/",
    parameters: list[dict] | None = None,
    request_schema: dict | None = None,
) -> FullEndpoint:
    """Build a FullEndpoint pydantic model with the OpenAPI-native list form
    for `parameters` (CL-6 accepts both list and dict forms)."""
    return FullEndpoint.model_validate(
        {
            "operationId": op_id,
            "method": method,
            "path": path,
            "description": f"summary for {op_id}",
            "tags": ["samples"],
            "parameters": parameters
            if parameters is not None
            else [
                {
                    "name": "project_id",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "request_schema": request_schema or {},
            "response_schema": {"type": "object"},
            "relevance_score": score,
        }
    )


@pytest.fixture
def fake_session():
    session = MagicMock()
    session.session_id = "session-abc"
    return session


@pytest.fixture
def mock_schema_rag_client(fake_session: MagicMock):
    with patch.object(fetch_spec, "SchemaRAGClient") as cls:
        instance = MagicMock()
        instance.current_session_state.return_value = fake_session
        cls.return_value.__enter__.return_value = instance
        cls.return_value.__exit__.return_value = False
        yield instance


@pytest.fixture
def mock_nextseek_client():
    with patch.object(fetch_spec, "NextseekClient") as cls:
        instance = MagicMock()
        cls.return_value.__enter__.return_value = instance
        cls.return_value.__exit__.return_value = False
        yield instance


@pytest.fixture
def mock_load_environment(fake_config: NextseekConfig):
    with patch.object(
        fetch_spec, "load_environment", return_value=fake_config
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# build_request_spec_template — pure unit tests
# ---------------------------------------------------------------------------


def test_template_for_get_with_path_param() -> None:
    full = {
        "operation_id": "GetAssay",
        "method": "GET",
        "endpoint": "/nextseek_api/assays/{uid}/",
        "parameters": [
            {"name": "uid", "in": "path", "required": True},
            {"name": "include", "in": "query", "required": False},
        ],
        "request_schema": {},
        "response_schema": {},
    }
    tmpl = fetch_spec.build_request_spec_template(full)
    assert tmpl["operation_id"] == "GetAssay"
    assert tmpl["method"] == "GET"
    assert tmpl["endpoint"] == "/nextseek_api/assays/{uid}/"
    assert tmpl["path_params"] == {"uid": "<value>"}
    assert tmpl["query_params"] == {}  # optional not included
    assert tmpl["headers"] == {}
    assert tmpl["request_body"] is None


def test_template_for_post_with_required_query_and_body() -> None:
    full = {
        "operation_id": "CreateThing",
        "method": "POST",
        "endpoint": "/nextseek_api/things/",
        "parameters": [
            {"name": "project_id", "in": "query", "required": True},
        ],
        "request_schema": {
            "type": "object",
            "required": ["name", "count", "active"],
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "active": {"type": "boolean"},
                "extra": {"type": "string"},  # optional, NOT emitted
            },
        },
    }
    tmpl = fetch_spec.build_request_spec_template(full)
    assert tmpl["method"] == "POST"
    assert tmpl["query_params"] == {"project_id": "<value>"}
    assert tmpl["request_body"] == {
        "name": "<string>",
        "count": 0,
        "active": False,
    }


def test_template_handles_dict_keyed_parameters() -> None:
    """Legacy parameters-as-dict shape (CL-6) normalizes to list."""
    full = {
        "operation_id": "GetX",
        "method": "GET",
        "endpoint": "/x/{uid}/",
        "parameters": {"uid": {"in": "path", "required": True}},
    }
    tmpl = fetch_spec.build_request_spec_template(full)
    assert tmpl["path_params"] == {"uid": "<value>"}


def test_template_body_null_for_get_even_with_schema() -> None:
    full = {
        "operation_id": "ListX",
        "method": "GET",
        "endpoint": "/x/",
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    }
    tmpl = fetch_spec.build_request_spec_template(full)
    assert tmpl["request_body"] is None


def test_template_post_no_schema_emits_empty_body() -> None:
    full = {
        "operation_id": "Ping",
        "method": "POST",
        "endpoint": "/ping/",
        "parameters": [],
    }
    tmpl = fetch_spec.build_request_spec_template(full)
    assert tmpl["request_body"] == {}


def test_skeleton_unknown_type_falls_back_to_value_placeholder() -> None:
    schema = {
        "type": "object",
        "required": ["weird"],
        "properties": {"weird": {"type": "definitely-not-real"}},
    }
    out = fetch_spec._skeleton_from_schema(schema)
    assert out == {"weird": "<value>"}


def test_skeleton_non_object_returns_empty() -> None:
    assert fetch_spec._skeleton_from_schema({"type": "array"}) == {}
    assert fetch_spec._skeleton_from_schema(None) == {}


# ---------------------------------------------------------------------------
# main() — stdout shape tests
# ---------------------------------------------------------------------------


def test_main_emits_spec_and_template(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "GetAssay",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "spec" in out and "request_spec_template" in out
    assert out["spec"]["operation_id"] == "GetAssay"
    assert out["request_spec_template"]["operation_id"] == "GetAssay"
    assert out["request_spec_template"]["method"] == "GET"
    assert (
        out["request_spec_template"]["endpoint"]
        == "/nextseek_api/samples/"
    )


def test_main_print_example_emits_only_template(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "GetAssay",
            "--print-example",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out.keys()) == {
        "operation_id",
        "method",
        "endpoint",
        "path_params",
        "query_params",
        "headers",
        "request_body",
    }


def test_main_stderr_lists_optional_query_params(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "ListAssays",
        parameters=[
            {"name": "project_id", "in": "query", "required": True},
            {"name": "page", "in": "query", "required": False},
            {"name": "limit", "in": "query", "required": False},
        ],
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "ListAssays",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "optional query params" in captured.err
    assert "page" in captured.err
    assert "limit" in captured.err


def test_help_contains_example(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        fetch_spec.main(["--help"])
    out = capsys.readouterr().out
    assert "--print-example" in out
    assert "operation_id" in out or "operation-id" in out


# ---------------------------------------------------------------------------
# Lazy cache — DD-7
# ---------------------------------------------------------------------------


def test_lazy_cache_writes_on_first_fetch(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "GetAssay",
        ]
    )
    assert rc == 0
    cached = resolve_endpoint_full_path("dev", "GetAssay")
    assert cached.exists()
    data = json.loads(cached.read_text())
    assert data["session_id"] == "session-abc"
    assert data["spec"]["operation_id"] == "GetAssay"
    assert mock_schema_rag_client.retrieve_full.call_count == 1


def test_lazy_cache_read_on_second_fetch(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    argv = [
        "--env",
        "dev",
        "--env-file",
        str(fake_env_file),
        "--operation-id",
        "GetAssay",
    ]
    assert fetch_spec.main(argv) == 0
    assert fetch_spec.main(argv) == 0
    # Second call must NOT re-hit SchemaRAG.
    assert mock_schema_rag_client.retrieve_full.call_count == 1


def test_lazy_cache_invalidated_on_session_change(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    argv = [
        "--env",
        "dev",
        "--env-file",
        str(fake_env_file),
        "--operation-id",
        "GetAssay",
    ]
    assert fetch_spec.main(argv) == 0

    # Simulate reingest: new session id.
    new_session = MagicMock()
    new_session.session_id = "session-xyz"
    mock_schema_rag_client.current_session_state.return_value = new_session

    assert fetch_spec.main(argv) == 0
    # Second call must re-hit SchemaRAG because session_id flipped.
    assert mock_schema_rag_client.retrieve_full.call_count == 2
    # Cached file now stamped with new session_id.
    data = json.loads(resolve_endpoint_full_path("dev", "GetAssay").read_text())
    assert data["session_id"] == "session-xyz"


def test_lazy_cache_ignores_corrupt_cache_file(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    # Seed a garbage cache file; should be silently overwritten on fetch.
    cache_file = resolve_endpoint_full_path("dev", "GetAssay")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("not json at all {{{")

    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "GetAssay",
        ]
    )
    assert rc == 0
    data = json.loads(cache_file.read_text())
    assert data["spec"]["operation_id"] == "GetAssay"


def test_lazy_fetch_unknown_op_raises_lookup_error(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contract pin for Task 08's resolve_operation."""
    mock_schema_rag_client.retrieve_full.side_effect = LookupError(
        "no endpoint with operation_id='DoesNotExist'"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "DoesNotExist",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "DoesNotExist" in err


def test_no_cache_flag_bypasses_lazy_cache(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    """--no-cache falls through to the legacy retrieve_with_auto_ingest path."""
    mock_schema_rag_client.retrieve_with_auto_ingest.return_value = (
        SchemaRAGResponse(
            query="GetAssay",
            endpoints=[_make_full_endpoint("GetAssay")],
            total_results=1,
        )
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "GetAssay",
            "--no-cache",
        ]
    )
    assert rc == 0
    # retrieve_full (the lazy path) must NOT be called when --no-cache is set.
    mock_schema_rag_client.retrieve_full.assert_not_called()
    mock_schema_rag_client.retrieve_with_auto_ingest.assert_called_once()


# ---------------------------------------------------------------------------
# Legacy --query path (semantic search)
# ---------------------------------------------------------------------------


def test_query_path_returns_top_result(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_with_auto_ingest.return_value = (
        SchemaRAGResponse(
            query="how do I get a single sample",
            endpoints=[
                _make_full_endpoint("samples_list", 0.55),
                _make_full_endpoint("samples_get", 0.97),  # highest
                _make_full_endpoint("projects_list", 0.30),
            ],
            total_results=3,
        )
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--query",
            "how do I get a single sample",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["spec"]["operation_id"] == "samples_get"
    assert out["spec"]["relevance_score"] == pytest.approx(0.97)
    # Cache written with session_id wrapper.
    cached = resolve_endpoint_full_path("dev", "samples_get")
    assert cached.exists()
    data = json.loads(cached.read_text())
    assert data["session_id"] == "session-abc"


def test_query_path_no_results_exit_1(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_with_auto_ingest.return_value = (
        SchemaRAGResponse(query="nada", endpoints=[], total_results=0)
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--query",
            "nada",
        ]
    )
    assert rc == 1
    assert "No results" in capsys.readouterr().err


def test_query_path_api_error_exit_2(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.retrieve_with_auto_ingest.side_effect = RuntimeError(
        "upstream 500"
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--query",
            "whatever",
        ]
    )
    assert rc == 2
    assert "upstream 500" in capsys.readouterr().err


def test_missing_session_exits_config(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_schema_rag_client.current_session_state.return_value = None
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "anything",
        ]
    )
    assert rc == 3
    assert "no session" in capsys.readouterr().err.lower()


def test_legacy_path_op_id_not_found(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--operation-id --no-cache still needs a match in the results."""
    mock_schema_rag_client.retrieve_with_auto_ingest.return_value = (
        SchemaRAGResponse(
            query="x",
            endpoints=[_make_full_endpoint("somebody_else", 0.9)],
            total_results=1,
        )
    )
    rc = fetch_spec.main(
        [
            "--env",
            "dev",
            "--env-file",
            str(fake_env_file),
            "--operation-id",
            "not_in_response",
            "--no-cache",
        ]
    )
    assert rc == 1
    assert "No match" in capsys.readouterr().err


def test_argv_defaults_to_sys_argv(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    """main() must read sys.argv[1:] when argv is None (test_bin_shims expects this)."""
    mock_schema_rag_client.retrieve_full.return_value = _make_full_endpoint(
        "GetAssay"
    )
    argv = [
        "fetch_spec.py",
        "--env",
        "dev",
        "--env-file",
        str(fake_env_file),
        "--operation-id",
        "GetAssay",
    ]
    with patch.object(sys, "argv", argv):
        rc = fetch_spec.main()
    assert rc == 0
