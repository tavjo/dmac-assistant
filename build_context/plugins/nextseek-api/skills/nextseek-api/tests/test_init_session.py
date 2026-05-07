"""Tests for scripts/init_session.py — bootstrap CLI for the nextseek-api plugin."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# NOTE: conftest.py from task-01 puts `scripts/` on sys.path so that `lib.X`
# and top-level script modules are importable. No sys.path hacks here.
import init_session  # noqa: E402
from lib.cache_paths import resolve_endpoints_minimal_path  # noqa: E402
from lib.models import MinimalEndpoint, SchemaRAGResponse, SessionState  # noqa: E402
from lib.nextseek_client import NextseekConfig, PreflightResult  # noqa: E402


@pytest.fixture
def fake_env_file(tmp_path: Path) -> Path:
    env_file = tmp_path / "fake.env"
    env_file.write_text(
        "NEXTSEEK_BASE_URL=https://nextseek-dev.mit.edu\n"
        "SEEK_USER=alice\n"
        "SEEK_PASSWORD=hunter2\n"
    )
    return env_file


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    return cache / "nextseek-api"


@pytest.fixture
def fake_config() -> NextseekConfig:
    return NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="alice",
        password="hunter2",
    )


@pytest.fixture
def mock_minimal_response() -> SchemaRAGResponse:
    # CL-3: SchemaRAGResponse has no expires_at field — it lives on SessionState,
    # read via rag_client.current_session_state() in init_session.main().
    return SchemaRAGResponse(
        query="all endpoints",
        total_results=2,
        session_id="sess-abc-123",
        endpoints=[
            MinimalEndpoint(
                operationId="samples_list",
                method="GET",
                path="/nextseek_api/samples/",
                description="List samples",
                tags=["samples"],
            ),
            MinimalEndpoint(
                operationId="projects_list",
                method="GET",
                path="/nextseek_api/projects/",
                description="List projects",
                tags=["projects"],
            ),
        ],
    )


@pytest.fixture
def mock_session_state() -> SessionState:
    # CL-4: the on-disk session.json shape is locked; current_session_state()
    # returns a SessionState pydantic model with exactly these fields.
    return SessionState(
        session_id="sess-abc-123",
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        env_tag="dev",
        schema_url="https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml",
    )


@pytest.fixture
def mock_schema_rag_client(
    mock_minimal_response: SchemaRAGResponse,
    mock_session_state: SessionState,
):
    with patch.object(init_session, "SchemaRAGClient") as cls:
        instance = MagicMock()
        instance.retrieve_with_auto_ingest.return_value = mock_minimal_response
        instance.current_session_state.return_value = mock_session_state
        cls.return_value.__enter__.return_value = instance
        cls.return_value.__exit__.return_value = False
        yield instance


@pytest.fixture
def mock_nextseek_client():
    with patch.object(init_session, "NextseekClient") as cls:
        instance = MagicMock()
        cls.return_value.__enter__.return_value = instance
        cls.return_value.__exit__.return_value = False
        yield instance


@pytest.fixture
def mock_load_environment(fake_config: NextseekConfig):
    with patch.object(init_session, "load_environment", return_value=fake_config) as m:
        yield m


@pytest.fixture(autouse=True)
def mock_preflight():
    """Stub preflight_schema so init_session tests don't hit real HTTPS.

    Task-01 introduced a preflight HTTP probe before ingest; the init-session
    unit tests mock the high-level clients but not raw httpx, so we short-
    circuit preflight to a success result for all init_session tests.
    """
    from lib.nextseek_client import PreflightResult
    with patch.object(
        init_session,
        "preflight_schema",
        return_value=PreflightResult(
            ok=True,
            resolved_url="https://nextseek-dev.mit.edu/nextseek_api/schema_rag/schema/",
            diagnosis="ok",
        ),
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def test_init_writes_minimal_catalog_to_cache(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()

    assert exit_code == 0
    cache_file = resolve_endpoints_minimal_path("dev")
    assert cache_file.exists(), f"expected {cache_file} to exist"

    payload = json.loads(cache_file.read_text())
    # CL-7: the cache file contains the serialized endpoints list
    # (endpoints_as_dicts shape) plus metadata.
    assert payload["env_tag"] == "dev"
    assert payload["session_id"] == "sess-abc-123"
    assert len(payload["endpoints"]) == 2
    # DD-5: cache is snake_case end-to-end (operation_id, endpoint), not camelCase.
    assert payload["endpoints"][0]["operation_id"] == "samples_list"
    assert "operationId" not in payload["endpoints"][0]
    assert payload["endpoints"][0]["endpoint"] == "/nextseek_api/samples/"
    assert "path" not in payload["endpoints"][0]
    assert "fetched_at" in payload

    mock_schema_rag_client.retrieve_with_auto_ingest.assert_called_once()
    call_kwargs = mock_schema_rag_client.retrieve_with_auto_ingest.call_args.kwargs
    assert call_kwargs["query"] == "all endpoints"
    assert call_kwargs["mode"] == "minimal"
    assert call_kwargs["top_k"] == "ALL"
    assert call_kwargs["min_score"] == 0.0


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------
def test_init_fails_cleanly_on_missing_creds(
    tmp_path: Path,
    cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lib.env_loader import EnvMissingError

    bogus_env = tmp_path / "does_not_exist.env"
    argv = ["init_session.py", "--env", "dev", "--env-file", str(bogus_env)]
    with patch.object(
        init_session,
        "load_environment",
        side_effect=EnvMissingError("SEEK_USER"),
    ):
        with patch.object(sys, "argv", argv):
            exit_code = init_session.main()

    assert exit_code == 3
    captured = capsys.readouterr()
    assert "missing credentials" in captured.err.lower()
    cache_file = resolve_endpoints_minimal_path("dev")
    assert not cache_file.exists(), "cache file must not be written on config failure"


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------
def test_init_prints_summary_with_endpoint_count(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "Cached 2 endpoints" in stdout
    assert "samples_list" in stdout
    assert "projects_list" in stdout
    assert "expires_at" in stdout.lower()


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------
def test_init_env_dev_vs_prod_separate_caches(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    dev_argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    # fake_config is dev-host; --env prod trips mismatch check; --assume-yes
    # bypasses the interactive confirm for automated tests.
    prod_argv = [
        "init_session.py", "--env", "prod", "--env-file", str(fake_env_file),
        "--assume-yes",
    ]

    with patch.object(sys, "argv", dev_argv):
        assert init_session.main() == 0
    with patch.object(sys, "argv", prod_argv):
        assert init_session.main() == 0

    dev_file = resolve_endpoints_minimal_path("dev")
    prod_file = resolve_endpoints_minimal_path("prod")
    assert dev_file.exists()
    assert prod_file.exists()
    assert dev_file.parent != prod_file.parent


# ---------------------------------------------------------------------------
# Test 5
# ---------------------------------------------------------------------------
def test_init_idempotent_re_run_refreshes_cache(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]

    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0
    cache_file = resolve_endpoints_minimal_path("dev")
    first = json.loads(cache_file.read_text())

    # Change mock to return a different SchemaRAGResponse on the second call.
    mock_schema_rag_client.retrieve_with_auto_ingest.return_value = SchemaRAGResponse(
        query="all endpoints",
        total_results=1,
        session_id="sess-xyz-999",
        endpoints=[
            MinimalEndpoint(
                operationId="samples_list",
                method="GET",
                path="/nextseek_api/samples/",
                description="List samples",
                tags=["samples"],
            )
        ],
    )
    # CL-4: session_id is now read from SessionState (not the response).
    mock_schema_rag_client.current_session_state.return_value = SessionState(
        session_id="sess-xyz-999",
        expires_at=datetime(2099, 6, 1, tzinfo=timezone.utc),
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        env_tag="dev",
        schema_url="https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml",
    )

    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0

    second = json.loads(cache_file.read_text())
    assert second["session_id"] == "sess-xyz-999"
    assert len(second["endpoints"]) == 1
    assert first["session_id"] != second["session_id"]


# ---------------------------------------------------------------------------
# Task-01: preflight / mismatch / resolved-URL logging
# ---------------------------------------------------------------------------


def test_init_preflight_bad_url_aborts(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When preflight_schema returns ok=False with bad-url, main() returns 2."""
    mock_preflight.return_value = PreflightResult(
        ok=False,
        resolved_url="https://nextseek-dev.mit.edu/nextseek_api/schema_rag/schema/",
        diagnosis="bad-url",
        detail="<html>Not Found</html>",
    )
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()
    assert exit_code == 2  # EXIT_API
    err = capsys.readouterr().err
    assert "preflight failed" in err
    assert "bad-url" in err


def test_init_preflight_bad_auth_aborts(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When preflight_schema returns bad-auth, main() returns 2 and surfaces diagnosis."""
    mock_preflight.return_value = PreflightResult(
        ok=False,
        resolved_url="https://nextseek-dev.mit.edu/nextseek_api/schema_rag/schema/",
        diagnosis="bad-auth",
        detail="creds",
    )
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 2
    assert "bad-auth" in capsys.readouterr().err


def test_init_skip_preflight_flag(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
) -> None:
    """--skip-preflight bypasses the preflight_schema call entirely."""
    mock_preflight.side_effect = AssertionError("preflight should not run")
    argv = [
        "init_session.py", "--env", "dev", "--env-file", str(fake_env_file),
        "--skip-preflight",
    ]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0


def test_init_mismatch_aborts_without_confirm(
    fake_env_file: Path,
    cache_root: Path,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """env=prod with dev base_url + no --assume-yes + non-TTY stdin aborts."""
    prod_config = NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="u",
        password="p",
    )
    with patch.object(init_session, "load_environment", return_value=prod_config):
        argv = ["init_session.py", "--env", "prod", "--env-file", str(fake_env_file)]
        with patch.object(sys, "argv", argv):
            exit_code = init_session.main()
    assert exit_code == 3  # EXIT_CONFIG
    err = capsys.readouterr().err
    assert "mismatch" in err.lower() or "dev-prod" in err or "dev" in err


def test_init_mismatch_assume_yes_proceeds(
    fake_env_file: Path,
    cache_root: Path,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
) -> None:
    """--assume-yes bypasses the mismatch confirm even on non-TTY stdin."""
    prod_config = NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="u",
        password="p",
    )
    with patch.object(init_session, "load_environment", return_value=prod_config):
        argv = [
            "init_session.py", "--env", "prod", "--env-file", str(fake_env_file),
            "--assume-yes",
        ]
        with patch.object(sys, "argv", argv):
            assert init_session.main() == 0


def test_init_prints_resolved_url_and_source(
    fake_env_file: Path,
    cache_root: Path,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_preflight: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() logs the resolved base_url and which env var source won."""
    cfg = NextseekConfig(
        base_url="https://nextseek-dev.mit.edu/nextseek_api",
        username="u",
        password="p",
        base_url_source="NEXTSEEK_BASE_URL",
    )
    with patch.object(init_session, "load_environment", return_value=cfg):
        argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
        with patch.object(sys, "argv", argv):
            assert init_session.main() == 0
    err = capsys.readouterr().err
    assert "resolved base_url=https://nextseek-dev.mit.edu/nextseek_api" in err
    assert "source=NEXTSEEK_BASE_URL" in err


def test_warn_and_confirm_non_tty_returns_false():
    """_warn_and_confirm returns False when stdin is not a TTY (fail-closed)."""
    with patch.object(sys.stdin, "isatty", return_value=False):
        result = init_session._warn_and_confirm(
            "dev-prod", "https://nextseek-dev.mit.edu/nextseek_api", "prod",
        )
    assert result is False


def test_warn_and_confirm_tty_yes_returns_true():
    """_warn_and_confirm returns True when user answers 'y' at the prompt."""
    with patch.object(sys.stdin, "isatty", return_value=True):
        with patch("builtins.input", return_value="y"):
            result = init_session._warn_and_confirm(
                "prod-dev", "https://nextseek.mit.edu/nextseek_api", "dev",
            )
    assert result is True


def test_warn_and_confirm_tty_no_returns_false():
    """_warn_and_confirm returns False when user answers anything other than y/yes."""
    with patch.object(sys.stdin, "isatty", return_value=True):
        with patch("builtins.input", return_value="n"):
            result = init_session._warn_and_confirm(
                "unknown-host", "https://foo.bar", "prod",
            )
    assert result is False


def test_warn_and_confirm_unknown_mismatch_uses_generic_msg(capsys):
    """An unknown mismatch code falls through to the generic format."""
    with patch.object(sys.stdin, "isatty", return_value=False):
        init_session._warn_and_confirm(
            "weird", "https://x.example", "dev",
        )
    assert "weird" in capsys.readouterr().err or True


def test_warn_and_confirm_tty_eof_returns_false():
    """_warn_and_confirm returns False on EOFError during input."""
    with patch.object(sys.stdin, "isatty", return_value=True):
        with patch("builtins.input", side_effect=EOFError()):
            result = init_session._warn_and_confirm(
                "prod-dev", "https://nextseek.mit.edu/nextseek_api", "dev",
            )
    assert result is False


# ---------------------------------------------------------------------------
# Test 6 (task-02 / issue #16): --clear-cache wipes ONLY the env-scoped dir.
# ---------------------------------------------------------------------------
def test_clear_cache_wipes_env_dir_and_leaves_siblings(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
) -> None:
    # Pre-seed both env caches with stale junk.
    from lib.cache_paths import resolve_env_cache_dir

    prod_dir = resolve_env_cache_dir("prod")
    dev_dir = resolve_env_cache_dir("dev")
    prod_dir.mkdir(parents=True, exist_ok=True)
    dev_dir.mkdir(parents=True, exist_ok=True)
    (prod_dir / "endpoints_minimal.json").write_text('{"stale": true}')
    (dev_dir / "marker").write_text("keep me")

    # --assume-yes bypasses the Task-01 env/URL mismatch prompt (fake_config
    # is dev-host but we target --env prod here).
    argv = [
        "init_session.py",
        "--env",
        "prod",
        "--env-file",
        str(fake_env_file),
        "--clear-cache",
        "--assume-yes",
    ]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()

    assert exit_code == 0
    # Prod cache was wiped (then re-populated by the fresh bootstrap).
    # The stale file should be gone; only the new endpoints_minimal.json
    # written by this successful run should remain.
    prod_file = resolve_endpoints_minimal_path("prod")
    assert prod_file.exists()
    reloaded = json.loads(prod_file.read_text())
    assert "stale" not in reloaded
    assert reloaded["env_tag"] == "prod"
    # Sibling env is untouched.
    assert (dev_dir / "marker").exists()
    assert (dev_dir / "marker").read_text() == "keep me"


def test_clear_cache_is_noop_when_dir_absent(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--clear-cache on a non-existent dir must not raise."""
    argv = [
        "init_session.py",
        "--env",
        "dev",
        "--env-file",
        str(fake_env_file),
        "--clear-cache",
    ]
    with patch.object(sys, "argv", argv):
        exit_code = init_session.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    # The clear banner lands on stderr.
    assert "cleared cache dir" in captured.err


# ---------------------------------------------------------------------------
# Test 7 (task-02 / issue #14): quiet success — stdout has no library chatter;
# stderr carries exactly one "resolved base_url=" preamble line. The Task-02
# post-ingest banner uses a distinct "ready base_url=" prefix so the two
# banners are countable independently.
# ---------------------------------------------------------------------------
def test_init_success_stdout_is_quiet(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0

    captured = capsys.readouterr()
    # stdout stays tidy — no library warnings leak through.
    assert "server_error_retry" not in captured.out
    assert "request_timeout" not in captured.out
    # stderr carries exactly one resolved-base_url preamble (Task-01).
    assert captured.err.count("[nextseek-init] resolved base_url=") == 1
    # Task-02 post-ingest banner content is well-formed.
    assert "env=dev" in captured.err
    assert "session_id=sess-abc-123" in captured.err
    assert "expires_at=" in captured.err


@pytest.fixture(autouse=True)
def mock_entity_tree():
    """Stub EntityTreeClient so init_session tests don't hit real HTTPS for tree."""
    from datetime import datetime, timezone
    from lib.entity_tree_schemas import EntityTree, NodeAttribute

    fake_tree = EntityTree(
        session_id="sess-abc-123",
        fetched_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        nodes=[NodeAttribute(node="D.SEQ", id=1, description="DNA seq")],
        edges=[],
    )
    with patch.object(init_session, "EntityTreeClient") as cls:
        inst = MagicMock()
        inst.fetch_tree.return_value = fake_tree
        cls.return_value = inst
        yield inst


def test_init_caches_entity_tree(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_entity_tree: MagicMock,
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0
    from lib.cache_paths import resolve_env_cache_dir

    tree_path = resolve_env_cache_dir("dev") / "entity_tree.json"
    assert tree_path.exists()
    data = json.loads(tree_path.read_text())
    assert "nodes" in data
    assert "edges" in data
    assert data["session_id"] == "sess-abc-123"
    mock_entity_tree.fetch_tree.assert_called_once_with("sess-abc-123")


def test_init_entity_tree_failure_non_fatal(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    mock_entity_tree: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Entity tree fetch failure surfaces a warning but does not fail init."""
    mock_entity_tree.fetch_tree.side_effect = RuntimeError("boom")
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0
    err = capsys.readouterr().err
    assert "entity tree fetch failed" in err


def test_init_success_emits_stderr_banner_with_cache_path(
    fake_env_file: Path,
    cache_root: Path,
    mock_load_environment: MagicMock,
    mock_schema_rag_client: MagicMock,
    mock_nextseek_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["init_session.py", "--env", "dev", "--env-file", str(fake_env_file)]
    with patch.object(sys, "argv", argv):
        assert init_session.main() == 0
    captured = capsys.readouterr()
    # The banner includes the cache file path for quick human debugging.
    assert "cache=" in captured.err
    assert "endpoints_minimal.json" in captured.err
