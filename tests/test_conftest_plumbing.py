"""Contract tests for the shared conftest.py extensions."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import tests.harness  # noqa: F401

from build_tools.verify_env import REQUIRED_VARS


pytest_plugins = ("pytester",)


@pytest.fixture(autouse=True)
def _scrub_live_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the in-process pytester children hermetic against env pollution.

    ``live_env`` merges ``{**file_values, **os.environ}`` — os.environ wins.
    Earlier tests in the full suite call ``load_config()``, whose
    ``load_dotenv(_REPO_ROOT / ".env", override=False)`` loads the REAL repo
    .env into this process's os.environ; the pytester child inherits it and
    the real values shadow the fake .env these tests write (task-0R4: solo
    pass / full-suite fail, plus real secret values in failure output).
    """
    for key in REQUIRED_VARS:
        monkeypatch.delenv(key, raising=False)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFTEST_TEMPLATE = (_REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
_CONFTEST_SRC = _CONFTEST_TEMPLATE.replace(
    "from __future__ import annotations\n\n",
    "from __future__ import annotations\n\n"
    f"import sys\nsys.path.insert(0, {str(_REPO_ROOT)!r})\n\n",
    1,
)


def test_live_marker_registered(pytestconfig: pytest.Config) -> None:
    markers = {m.split(":", 1)[0].strip() for m in pytestconfig.getini("markers")}
    assert "live" in markers


def test_live_env_fixture_skips_when_env_missing(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_uses_live=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_lives(live_env):
                assert False, "should have been skipped"
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(skipped=1)


def test_live_env_fixture_provides_vars_when_env_present(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_CONFTEST_SRC)
    # conftest._locate_env_file() walks UP from the conftest's own dir
    # (pytester.path) to find .env; it does NOT read $HOME (changed in 8460d8f,
    # 2026-05-06). Put the fake .env where that walk-up reaches it.
    (pytester.path / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    pytester.makepyfile(
        test_uses_live=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_lives(live_env):
                assert live_env["AWS_REGION"] == "us-east-1"
                assert live_env["NEXTSEEK_URL"].startswith("https://")
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)


def test_live_socket_fixture_allows_computed_bedrock_and_nextseek_hosts(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_CONFTEST_SRC)
    # See note above: the fake .env must live where _locate_env_file()'s
    # walk-up from the conftest dir reaches it, not in $HOME.
    (pytester.path / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    pytester.makepyfile(
        test_sockets=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_allowed_hosts(live_env, live_socket):
                allowed = live_socket["allowed_hosts"]
                assert "bedrock-runtime.us-east-1.amazonaws.com" in allowed
                assert "nextseek-dev.example.mit.edu" in allowed
                assert not any("*" in host for host in allowed), allowed
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)


def test_live_socket_is_session_scoped(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_scope=textwrap.dedent(
            """
            def test_fixture_is_session_scoped(request):
                fixdef = request._fixturemanager.getfixturedefs("live_socket", request.node)
                assert fixdef is not None
                assert fixdef[0].scope == "session"
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)


def test_terminal_hook_stays_silent_when_no_live_selected(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard must not fire when the user intentionally runs only non-live tests.

    With ~/.env loaded and zero live-marked tests selected (e.g., the user
    passed ``-m "not live"`` or the suite simply has no live tests), the
    guard must not fail the session. This is the canonical false-positive
    the original implementation failed to avoid.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_nothing_live=textwrap.dedent(
            """
            def test_plain():
                assert True
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert result.ret == 0
    assert "SESSION GUARD FAIL" not in result.stdout.str()


def test_terminal_hook_fails_when_live_selected_but_none_ran(
    pytester: pytest.Pytester,
) -> None:
    """Guard fires (non-zero exit) when live was selected but every test
    errored out before a call-phase pass OR skip — e.g., the env loaded,
    tests were collected, but every one raised a non-Skipped exception
    during setup. A guard-fire like this means something silently broke
    the live-test surface (fixtures, collection, import) without
    surfacing through pytest's own failure count.

    L-2 regression cover: a pure ``pytest.skip`` population does NOT
    fire this guard (see :func:`test_terminal_hook_silent_when_all_live_skip`).
    """
    pytester.makeconftest(_CONFTEST_SRC)
    # The guard requires env_loaded=True, which needs a .env on the conftest
    # dir's walk-up (not $HOME). See note in
    # test_live_env_fixture_provides_vars_when_env_present.
    (pytester.path / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    pytester.makepyfile(
        test_failing_live=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_errors():
                raise RuntimeError("simulated live-surface breakage")
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    assert result.ret != 0
    result.stdout.fnmatch_lines(
        ["*SESSION GUARD FAIL*live tests were selected but none actually ran*"]
    )


def test_terminal_hook_silent_when_all_live_skip(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-2 regression: ADR-004 hourly token expiry makes an all-skip outcome
    the *correct* behavior. The guard must not fire red on a pure-skip
    population; counting ``report.skipped`` alongside ``report.passed``
    is what enforces this.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=g\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_skipped_live=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_skips_at_call():
                pytest.skip("simulated ADR-004 expired-token skip")
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    assert result.ret == 0, result.stdout.str()
    assert "SESSION GUARD FAIL" not in result.stdout.str()


def test_terminal_hook_passes_when_env_absent(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_nothing_live=textwrap.dedent(
            """
            def test_plain():
                assert True
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
