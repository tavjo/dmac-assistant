"""Tests for scripts/call_request.py — unified nextseek-call CLI (task-08)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# conftest.py (task-01) puts scripts/ on sys.path.
import call_request  # noqa: E402
from lib.models import FullEndpoint, MinimalEndpoint, RequestSpec  # noqa: E402
from lib.nextseek_client import NextseekConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    env_dir = cache / "nextseek-api" / "v2" / "dev"
    (env_dir / "endpoints_full").mkdir(parents=True, exist_ok=True)
    return env_dir


@pytest.fixture
def fake_env_file(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(
        "NEXTSEEK_BASE_URL=https://nextseek-dev.mit.edu/nextseek_api\n"
        "SEEK_USER=alice\n"
        "SEEK_PASSWORD=hunter2\n"
    )
    return p


def _list_assays_full_dict() -> dict:
    return {
        "operation_id": "ListAssays",
        "method": "GET",
        "endpoint": "/nextseek_api/assays/",
        "description": "List assays",
        "tags": ["assays"],
        "parameters": [],
        "request_schema": {},
        "response_schema": {"type": "object"},
        "relevance_score": 0.95,
    }


def _create_thing_full_dict() -> dict:
    return {
        "operation_id": "CreateThing",
        "method": "POST",
        "endpoint": "/nextseek_api/things/",
        "description": "Create a thing",
        "tags": ["things"],
        "parameters": [],
        "request_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        "response_schema": {},
        "relevance_score": 0.9,
    }


@pytest.fixture
def patch_env(monkeypatch: pytest.MonkeyPatch) -> NextseekConfig:
    cfg = NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="u",
        password="p",
    )
    monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)
    return cfg


@pytest.fixture
def patch_resolve(monkeypatch: pytest.MonkeyPatch):
    """Stub _resolve_via_rag to return a configurable op dict."""
    state: dict = {"op": _list_assays_full_dict()}

    def _fake(op_arg, env_tag, env_file):
        return state["op"], None, MagicMock(session_id="session-abc")

    monkeypatch.setattr(call_request, "_resolve_via_rag", _fake)
    return state


# ---------------------------------------------------------------------------
# _load_json_arg
# ---------------------------------------------------------------------------


class TestLoadJsonArg:
    def test_literal_json(self):
        assert call_request._load_json_arg('{"a": 1}') == {"a": 1}

    def test_none(self):
        assert call_request._load_json_arg(None) is None

    def test_empty_string(self):
        assert call_request._load_json_arg("   ") is None

    def test_file_ref(self, tmp_path: Path):
        p = tmp_path / "payload.json"
        p.write_text(json.dumps({"hi": "there"}))
        assert call_request._load_json_arg(f"@{p}") == {"hi": "there"}


# ---------------------------------------------------------------------------
# build_spec
# ---------------------------------------------------------------------------


class TestBuildSpec:
    def test_get_with_query_params(self):
        op = _list_assays_full_dict()
        spec = call_request.build_spec(
            op, path_params={}, query_params={"page[size]": "500"}, body=None
        )
        assert isinstance(spec, RequestSpec)
        assert spec.operation_id == "ListAssays"
        assert spec.method == "GET"
        assert spec.query_params == {"page[size]": "500"}
        assert spec.request_body is None

    def test_post_with_body(self):
        op = _create_thing_full_dict()
        spec = call_request.build_spec(
            op, path_params=None, query_params=None, body={"name": "x"}
        )
        assert spec.method == "POST"
        assert spec.request_body == {"name": "x"}


# ---------------------------------------------------------------------------
# resolve_operation
# ---------------------------------------------------------------------------


class TestResolveOperation:
    def test_exact_match_returns_full(self, monkeypatch):
        want = _list_assays_full_dict()
        monkeypatch.setattr(
            "fetch_spec._lazy_fetch_full",
            lambda op_id, rag, env, sid, cache_base=None: want,
        )
        rag = MagicMock()
        got = call_request.resolve_operation("ListAssays", rag, "dev", "sid")
        assert got == want

    def test_single_search_hit(self, monkeypatch):
        calls: list[str] = []

        def fake_lazy(op_id, rag, env, sid, cache_base=None):
            calls.append(op_id)
            if len(calls) == 1:
                raise LookupError("nope")
            return _list_assays_full_dict()

        monkeypatch.setattr("fetch_spec._lazy_fetch_full", fake_lazy)

        rag = MagicMock()
        rag.retrieve_with_auto_ingest.return_value = MagicMock(
            endpoints=[
                MinimalEndpoint(operation_id="ListAssays", description="list")
            ]
        )
        got = call_request.resolve_operation("list the assays", rag, "dev", "sid")
        assert got["operation_id"] == "ListAssays"
        assert calls == ["list the assays", "ListAssays"]

    def test_zero_hits_exits_2(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "fetch_spec._lazy_fetch_full",
            lambda *a, **kw: (_ for _ in ()).throw(LookupError("nope")),
        )
        rag = MagicMock()
        rag.retrieve_with_auto_ingest.return_value = MagicMock(endpoints=[])
        with pytest.raises(SystemExit) as e:
            call_request.resolve_operation("gibberish", rag, "dev", "sid")
        assert e.value.code == call_request.EXIT_NO_MATCH
        assert "no operation matches" in capsys.readouterr().err

    def test_multi_hit_exits_with_listing(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "fetch_spec._lazy_fetch_full",
            lambda *a, **kw: (_ for _ in ()).throw(LookupError("nope")),
        )
        rag = MagicMock()
        rag.retrieve_with_auto_ingest.return_value = MagicMock(
            endpoints=[
                MinimalEndpoint(operation_id="ListAssays", description="one"),
                MinimalEndpoint(operation_id="ListStudies", description="two"),
            ]
        )
        with pytest.raises(SystemExit) as e:
            call_request.resolve_operation("list", rag, "dev", "sid")
        assert e.value.code == call_request.EXIT_AMBIGUOUS
        err = capsys.readouterr().err
        assert "multiple matches" in err.lower()
        assert "ListAssays" in err
        assert "ListStudies" in err


# ---------------------------------------------------------------------------
# main — end-to-end with stubs
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_dry_run_no_http(self, capsys, patch_env, patch_resolve):
        rc = call_request.main(
            ["--env", "dev", "--op", "ListAssays", "--dry-run"]
        )
        assert rc == call_request.EXIT_OK
        out = capsys.readouterr().out
        assert "dry-run OK" in out
        assert "/nextseek_api/assays/" in out

    def test_non_get_requires_confirmed_write(
        self, capsys, patch_env, patch_resolve
    ):
        patch_resolve["op"] = _create_thing_full_dict()
        rc = call_request.main(
            [
                "--env",
                "dev",
                "--op",
                "CreateThing",
                "--body",
                '{"name":"x"}',
            ]
        )
        assert rc == call_request.EXIT_CONFIRM_REQUIRED
        err = capsys.readouterr().err
        assert "--confirmed-write" in err

    def test_non_get_with_confirm_executes(
        self, capsys, patch_env, patch_resolve, monkeypatch
    ):
        patch_resolve["op"] = _create_thing_full_dict()
        fake_client = MagicMock()
        fake_client.request.return_value = {"id": 1}
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(
            [
                "--env",
                "dev",
                "--op",
                "CreateThing",
                "--body",
                '{"name":"x"}',
                "--confirmed-write",
            ]
        )
        assert rc == call_request.EXIT_OK
        fake_client.request.assert_called_once()
        args, kwargs = fake_client.request.call_args
        assert args[0] == "POST"
        assert kwargs["json"] == {"name": "x"}

    def test_spec_stdin_passthrough(self, capsys, monkeypatch):
        cfg = NextseekConfig(
            base_url="https://x.test/nextseek_api", username="u", password="p"
        )
        monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)
        fake_client = MagicMock()
        fake_client.request.return_value = {"results": []}
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        spec_json = json.dumps(
            {
                "operation_id": "ListAssays",
                "method": "GET",
                "endpoint": "/nextseek_api/assays/",
                "path_params": {},
                "query_params": {},
                "headers": {},
                "request_body": None,
            }
        )
        rc = call_request.main(["--env", "dev", "--spec", "-"], stdin_text=spec_json)
        assert rc == call_request.EXIT_OK
        fake_client.request.assert_called_once()

    def test_spec_from_file(self, tmp_path, monkeypatch):
        cfg = NextseekConfig(
            base_url="https://x.test/nextseek_api", username="u", password="p"
        )
        monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)
        fake_client = MagicMock()
        fake_client.request.return_value = {"ok": True}
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        spec_file = tmp_path / "s.json"
        spec_file.write_text(
            json.dumps(
                {
                    "operation_id": "ListAssays",
                    "method": "GET",
                    "endpoint": "/nextseek_api/assays/",
                    "path_params": {},
                    "query_params": {},
                    "headers": {},
                    "request_body": None,
                }
            )
        )
        rc = call_request.main(["--env", "dev", "--spec", str(spec_file)])
        assert rc == call_request.EXIT_OK

    def test_auto_paginate_aggregates(
        self, capsys, patch_env, patch_resolve, monkeypatch
    ):
        pages = [
            {"results": [{"i": 1}, {"i": 2}], "next": "p2", "count": 5},
            {"results": [{"i": 3}, {"i": 4}], "next": "p3", "count": 5},
            {"results": [{"i": 5}], "next": None, "count": 5},
        ]
        fake_client = MagicMock()
        fake_client.request.side_effect = pages
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(
            ["--env", "dev", "--op", "ListAssays", "--auto-paginate"]
        )
        assert rc == call_request.EXIT_OK
        out = json.loads(capsys.readouterr().out)
        assert len(out) == 5
        assert fake_client.request.call_count == 3

    def test_validate_failure_blocks_http(
        self, patch_env, patch_resolve, monkeypatch, capsys
    ):
        # Op requires a required query param 'project_id'; omit it -> validator fails.
        op = _list_assays_full_dict()
        op["parameters"] = [
            {
                "name": "project_id",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
            }
        ]
        patch_resolve["op"] = op

        # NextseekClient should NEVER be invoked; fail loudly if it is.
        cls = MagicMock(side_effect=AssertionError("HTTP must not run"))
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_VALIDATION
        # Structured error JSON printed to stderr.
        err = capsys.readouterr().err
        assert "MISSING_REQUIRED_PARAM" in err

    def test_neither_op_nor_spec_fails(self, capsys):
        rc = call_request.main(["--env", "dev"])
        assert rc == call_request.EXIT_FAIL
        assert "--op or --spec" in capsys.readouterr().err

    def test_bad_body_json_fails(self, capsys, patch_env):
        rc = call_request.main(
            ["--env", "dev", "--op", "ListAssays", "--body", "{not json"]
        )
        assert rc == call_request.EXIT_FAIL
        assert "parse flag JSON" in capsys.readouterr().err

    def test_bad_spec_json_fails(self, tmp_path, capsys):
        bad = tmp_path / "b.json"
        bad.write_text("not json at all")
        rc = call_request.main(["--env", "dev", "--spec", str(bad)])
        assert rc == call_request.EXIT_FAIL

    def test_spec_path_missing(self, capsys):
        rc = call_request.main(
            ["--env", "dev", "--spec", "/does/not/exist/zzz.json"]
        )
        assert rc == call_request.EXIT_FAIL

    def test_invalid_spec_pydantic(self, tmp_path, capsys):
        bad = tmp_path / "b.json"
        bad.write_text(json.dumps({"operation_id": "x"}))  # missing required fields
        rc = call_request.main(["--env", "dev", "--spec", str(bad)])
        assert rc == call_request.EXIT_FAIL

    def test_auto_paginate_non_get_warns(
        self, capsys, patch_env, patch_resolve, monkeypatch
    ):
        patch_resolve["op"] = _create_thing_full_dict()
        fake_client = MagicMock()
        fake_client.request.return_value = {"id": 1}
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(
            [
                "--env",
                "dev",
                "--op",
                "CreateThing",
                "--body",
                '{"name":"x"}',
                "--confirmed-write",
                "--auto-paginate",
            ]
        )
        assert rc == call_request.EXIT_OK
        err = capsys.readouterr().err
        assert "auto-paginate" in err.lower()

    def test_api_error_propagates(
        self, capsys, patch_env, patch_resolve, monkeypatch
    ):
        from lib.nextseek_client import NextseekAPIError

        fake_client = MagicMock()
        fake_client.request.side_effect = NextseekAPIError(
            "boom", status_code=500
        )
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_API

    def test_env_missing_returns_config(
        self, monkeypatch, patch_resolve, capsys
    ):
        from lib.env_loader import EnvMissingError

        def boom(**kw):
            raise EnvMissingError("no creds")

        monkeypatch.setattr(call_request, "load_environment", boom)
        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_CONFIG

    def test_env_file_honored(
        self, monkeypatch, patch_resolve, fake_env_file, capsys
    ):
        captured: dict = {}

        def fake_load(*, env_path=None, use_dev=False):
            captured["env_path"] = env_path
            captured["use_dev"] = use_dev
            return NextseekConfig(
                base_url="https://x/nextseek_api", username="u", password="p"
            )

        monkeypatch.setattr(call_request, "load_environment", fake_load)

        # Stub NextseekClient so the real HTTP path isn't exercised.
        fake_client = MagicMock()
        fake_client.request.return_value = {"ok": True}
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(
            [
                "--env",
                "dev",
                "--env-file",
                str(fake_env_file),
                "--op",
                "ListAssays",
            ]
        )
        assert rc == call_request.EXIT_OK
        assert captured["env_path"] == fake_env_file
        assert captured["use_dev"] is True


# ---------------------------------------------------------------------------
# _resolve_via_rag — session missing branch
# ---------------------------------------------------------------------------


class TestResolveViaRag:
    def test_session_missing_raises_config(self, monkeypatch, capsys):
        """When SchemaRAGClient has no session, main returns EXIT_CONFIG."""
        cfg = NextseekConfig(
            base_url="https://x/nextseek_api", username="u", password="p"
        )
        monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)

        rag_instance = MagicMock()
        rag_instance.current_session_state.return_value = None
        rag_cls = MagicMock()
        rag_cls.return_value.__enter__.return_value = rag_instance
        rag_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "SchemaRAGClient", rag_cls)

        http_cls = MagicMock()
        http_cls.return_value.__enter__.return_value = MagicMock()
        http_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", http_cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_CONFIG
        assert "no session" in capsys.readouterr().err.lower()

    def test_env_missing_in_resolve_branch(self, monkeypatch, capsys):
        """EnvMissingError raised during resolve -> EXIT_CONFIG."""
        from lib.env_loader import EnvMissingError

        def boom(**kw):
            raise EnvMissingError("bad env")

        monkeypatch.setattr(call_request, "load_environment", boom)
        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_CONFIG
        assert "missing credentials" in capsys.readouterr().err

    def test_api_error_in_resolve_branch(self, monkeypatch, capsys):
        """SchemaRAG HTTP error during op resolution -> EXIT_API."""
        from lib.nextseek_client import NextseekAPIError

        cfg = NextseekConfig(
            base_url="https://x/nextseek_api", username="u", password="p"
        )
        monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)

        rag_instance = MagicMock()
        rag_instance.current_session_state.return_value = MagicMock(
            session_id="sid"
        )
        rag_instance.retrieve_full.side_effect = NextseekAPIError(
            "schema rag down", status_code=500
        )
        rag_cls = MagicMock()
        rag_cls.return_value.__enter__.return_value = rag_instance
        rag_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "SchemaRAGClient", rag_cls)

        http_cls = MagicMock()
        http_cls.return_value.__enter__.return_value = MagicMock()
        http_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", http_cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_API

    def test_unexpected_error_in_resolve_branch(self, monkeypatch, capsys):
        """Unknown error during resolve -> EXIT_FAIL."""
        cfg = NextseekConfig(
            base_url="https://x/nextseek_api", username="u", password="p"
        )
        monkeypatch.setattr(call_request, "load_environment", lambda **kw: cfg)

        rag_instance = MagicMock()
        rag_instance.current_session_state.side_effect = RuntimeError("weird")
        rag_cls = MagicMock()
        rag_cls.return_value.__enter__.return_value = rag_instance
        rag_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "SchemaRAGClient", rag_cls)

        http_cls = MagicMock()
        http_cls.return_value.__enter__.return_value = MagicMock()
        http_cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", http_cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_FAIL


class TestExecutionErrors:
    def test_auth_error_on_execute(
        self, patch_env, patch_resolve, monkeypatch, capsys
    ):
        from lib.nextseek_client import NextseekAuthError

        fake_client = MagicMock()
        fake_client.request.side_effect = NextseekAuthError("bad auth")
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_API

    def test_timeout_on_execute(
        self, patch_env, patch_resolve, monkeypatch, capsys
    ):
        from lib.nextseek_client import NextseekTimeoutError

        fake_client = MagicMock()
        fake_client.request.side_effect = NextseekTimeoutError("slow")
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_API

    def test_generic_client_error_on_execute(
        self, patch_env, patch_resolve, monkeypatch, capsys
    ):
        from lib.nextseek_client import NextseekClientError

        fake_client = MagicMock()
        fake_client.request.side_effect = NextseekClientError("oops")
        cls = MagicMock()
        cls.return_value.__enter__.return_value = fake_client
        cls.return_value.__exit__.return_value = False
        monkeypatch.setattr(call_request, "NextseekClient", cls)

        rc = call_request.main(["--env", "dev", "--op", "ListAssays"])
        assert rc == call_request.EXIT_API

    def test_env_missing_at_final_execute_via_spec(
        self, monkeypatch, tmp_path, capsys
    ):
        """--spec path bypasses resolve; env failure on execute -> EXIT_CONFIG."""
        from lib.env_loader import EnvMissingError

        def boom(**kw):
            raise EnvMissingError("no creds")

        monkeypatch.setattr(call_request, "load_environment", boom)

        spec_file = tmp_path / "s.json"
        spec_file.write_text(
            json.dumps(
                {
                    "operation_id": "ListAssays",
                    "method": "GET",
                    "endpoint": "/nextseek_api/assays/",
                    "path_params": {},
                    "query_params": {},
                    "headers": {},
                    "request_body": None,
                }
            )
        )
        rc = call_request.main(["--env", "dev", "--spec", str(spec_file)])
        assert rc == call_request.EXIT_CONFIG


class TestAutoPaginateHelper:
    def test_non_dict_list_response(self, monkeypatch):
        client = MagicMock()
        client.request.side_effect = [
            [{"i": 1}, {"i": 2}],
            [],
        ]
        spec = RequestSpec(
            operation_id="ListAssays",
            method="GET",
            endpoint="/nextseek_api/assays/",
            path_params={},
            query_params={},
            headers={},
            request_body=None,
        )
        out = call_request._auto_paginate_get(client, spec, "/nextseek_api/assays/")
        assert len(out) == 2

    def test_none_results_treated_as_empty(self, monkeypatch):
        client = MagicMock()
        # dict without 'results' and not a list -> results=None branch
        client.request.return_value = {"unexpected": True}
        spec = RequestSpec(
            operation_id="ListAssays",
            method="GET",
            endpoint="/nextseek_api/assays/",
            path_params={},
            query_params={},
            headers={},
            request_body=None,
        )
        out = call_request._auto_paginate_get(client, spec, "/nextseek_api/assays/")
        assert out == []


class TestBuildSpecFailure:
    def test_build_spec_invalid_returns_fail(
        self, patch_env, patch_resolve, capsys
    ):
        # Empty operation_id from the op dict triggers pydantic min_length=1.
        patch_resolve["op"] = {
            "operation_id": "",
            "method": "GET",
            "endpoint": "/x/",
            "parameters": [],
            "request_schema": {},
            "response_schema": {},
            "tags": [],
        }
        rc = call_request.main(["--env", "dev", "--op", "anything"])
        assert rc == call_request.EXIT_FAIL
        assert "RequestSpec" in capsys.readouterr().err
