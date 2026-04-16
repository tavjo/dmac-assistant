"""Shared fixtures and autouse guards for the DMAC ingestion test suite."""
from __future__ import annotations

import html
import os
from importlib import import_module
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pytest

from build_tools.verify_env import REQUIRED_VARS, validate_env


_ENV_FILE = Path(os.path.expanduser("~/.env"))
_SESSION_LIVE_STATE: dict[str, object] = {"env_loaded": False, "live_ran": 0}


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


def make_synthetic_html(sections: Iterable[tuple[str, str]]) -> bytes:
    """Build deterministic HTML bytes from section title/paragraph tuples."""
    body_parts: list[str] = []
    for title, para in sections:
        body_parts.append(f"<h1>{html.escape(title)}</h1>")
        body_parts.append(f"<p>{html.escape(para)}</p>")
    body = "\n".join(body_parts)
    return f"<!DOCTYPE html><html><body>{body}</body></html>".encode("utf-8")


@pytest.fixture
def synthetic_html() -> bytes:
    """Default 3-section HTML fixture used by integration tests."""
    return make_synthetic_html(
        [
            ("Welcome", "Intro paragraph for the welcome page."),
            ("Getting Started", "Intro paragraph for getting started."),
            ("Sample Registration", "Intro paragraph for sample registration."),
        ]
    )


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


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" and report.passed and "live" in report.keywords:
        _SESSION_LIVE_STATE["live_ran"] = int(_SESSION_LIVE_STATE["live_ran"]) + 1


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del exitstatus, config
    if _SESSION_LIVE_STATE["env_loaded"] and int(_SESSION_LIVE_STATE["live_ran"]) == 0:
        terminalreporter.write_line(
            "SESSION GUARD FAIL: ~/.env loaded but no @pytest.mark.live tests "
            "actually ran (passed call phase).",
            red=True,
        )
        terminalreporter._session.exitstatus = pytest.ExitCode.TESTS_FAILED
