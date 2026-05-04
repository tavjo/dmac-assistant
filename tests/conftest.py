"""Shared fixtures and autouse guards for the DMAC ingestion test suite."""
from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from urllib.parse import urlparse

import pytest

from build_tools.verify_env import REQUIRED_VARS, validate_env


_ENV_FILE = Path(os.path.expanduser("~/.env"))
_SESSION_LIVE_STATE: dict[str, object] = {
    "env_loaded": False,
    "live_selected": 0,
    "live_ran": 0,
}


def _load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# The docs ingestion tests use Markdown-source fixtures directly. The bridge
# test suite must not depend on legacy HTML/PDF conversion helpers.


class _PoisonedPath:
    """Path-like object that raises on any filesystem use."""

    def __init__(self, label: str) -> None:
        self._label = label

    def __fspath__(self) -> str:
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            "Pass an explicit tmp_path override to ingest()."
        )

    def __str__(self) -> str:
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            "Pass an explicit tmp_path override to ingest()."
        )

    def __repr__(self) -> str:
        return f"<_PoisonedPath label={self._label!r}>"


@pytest.fixture(autouse=True)
def _block_production_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace production default paths with sentinels during tests."""
    try:
        constants = import_module("build_tools.ingest_nextseek_docs.constants")
    except ModuleNotFoundError:
        return

    monkeypatch.setattr(
        constants,
        "DEFAULT_DOCS_DIR",
        _PoisonedPath("DEFAULT_DOCS_DIR"),
        raising=True,
    )
    monkeypatch.setattr(
        constants,
        "DEFAULT_CLAUDE_MD_PATH",
        _PoisonedPath("DEFAULT_CLAUDE_MD_PATH"),
        raising=True,
    )


@pytest.fixture(scope="session")
def live_env() -> dict[str, str]:
    """Load ~/.env once for live tests and skip when it is absent or invalid."""
    file_values = _load_dotenv_file(_ENV_FILE)
    merged_values = {**file_values, **os.environ}

    if not file_values:
        pytest.skip(f"{_ENV_FILE} not found; skipping live test")

    _SESSION_LIVE_STATE["env_loaded"] = True
    errors = validate_env(merged_values)
    if errors:
        pytest.skip(f"{_ENV_FILE} present but invalid: {errors}")

    return {key: merged_values[key].strip() for key in REQUIRED_VARS}


@pytest.fixture(scope="session")
def live_socket(live_env: dict[str, str]) -> dict[str, list[str]]:
    """Temporarily enable sockets for the concrete live hosts only."""
    import pytest_socket

    allowed_hosts = [
        f"bedrock-runtime.{live_env['AWS_REGION']}.amazonaws.com",
        urlparse(live_env["NEXTSEEK_URL"]).hostname,
    ]
    allowed_hosts = [host for host in allowed_hosts if host]

    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(allowed_hosts, allow_unix_socket=True)
    try:
        yield {"allowed_hosts": allowed_hosts}
    finally:
        pytest_socket.disable_socket()


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    if _load_dotenv_file(_ENV_FILE):
        _SESSION_LIVE_STATE["env_loaded"] = True


def pytest_collection_finish(session: pytest.Session) -> None:
    _SESSION_LIVE_STATE["live_selected"] = sum(
        1 for item in session.items if "live" in item.keywords
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Count "handled correctly" outcomes for each selected live test.

    ADR-004: Bedrock bearer tokens expire hourly, so the intended behavior
    of a live run without fresh creds is to ``pytest.skip`` — not fail.
    Counting only ``report.passed`` made the session guard false-positive
    red on a full-skip run (all tokens expired → all live tests skip →
    ``live_ran`` stays 0 → guard fires red). We now count a ``call``-phase
    pass OR any skip report (setup or call) as "handled".

    Report cardinality invariant: setup-phase skip fires once (no call
    report follows); call-phase skip fires once (setup already passed);
    call-phase pass fires once. So each live test contributes at most one
    increment.
    """
    if "live" not in report.keywords:
        return
    if report.when == "call" and report.passed:
        _SESSION_LIVE_STATE["live_ran"] = int(_SESSION_LIVE_STATE["live_ran"]) + 1
    elif report.skipped and report.when in ("setup", "call"):
        _SESSION_LIVE_STATE["live_ran"] = int(_SESSION_LIVE_STATE["live_ran"]) + 1


def _live_guard_should_fail() -> bool:
    return (
        bool(_SESSION_LIVE_STATE["env_loaded"])
        and int(_SESSION_LIVE_STATE["live_selected"]) > 0
        and int(_SESSION_LIVE_STATE["live_ran"]) == 0
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Force a non-zero exit code when live tests were selected but none ran.

    `pytest_terminal_summary`-based enforcement does not affect pytest's
    return code: the exit status is computed before that hook fires. Moving
    the mutation into ``pytest_sessionfinish`` is the supported path
    (pytest docs: "You can set session.exitstatus in this hook").

    Also sweeps any leftover bridge containers by label. Per-test `finally`
    blocks miss containers when pytest is SIGKILL'd, the docker daemon
    hiccups mid-teardown, or a test error path bypasses cleanup. The sweep
    is label-scoped (`dmac.bridge=1`) so it never touches unrelated
    containers.
    """
    del exitstatus
    if _live_guard_should_fail():
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    _sweep_orphan_bridge_containers()


def _sweep_orphan_bridge_containers() -> None:
    """Best-effort: force-remove any surviving `dmac.bridge=1` containers."""
    try:
        import docker as _docker
    except ImportError:
        return
    try:
        client = _docker.from_env(timeout=5)
        client.ping()
    except Exception:
        return
    try:
        orphans = client.containers.list(
            all=True, filters={"label": ["dmac.bridge=1"]}
        )
    except Exception:
        return
    for container in orphans:
        try:
            container.remove(force=True)
        except Exception:  # noqa: BLE001 — best-effort, swallow quietly
            pass


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del exitstatus, config
    if _live_guard_should_fail():
        terminalreporter.write_line(
            "SESSION GUARD FAIL: ~/.env loaded and live tests were selected "
            "but none actually ran (passed call phase). Exiting non-zero.",
            red=True,
        )
