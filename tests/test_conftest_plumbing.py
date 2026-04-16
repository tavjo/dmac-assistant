"""Contract tests for the shared conftest.py extensions."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import tests.harness  # noqa: F401


pytest_plugins = ("pytester",)


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
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
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
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
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
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n",
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


def test_terminal_hook_fails_session_when_env_loaded_but_no_live_passed(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n",
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
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*SESSION GUARD FAIL*no @pytest.mark.live tests actually ran*"])


def test_terminal_hook_counts_only_passed_live_call_phase(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env").write_text(
        "AWS_BEARER_TOKEN_BEDROCK=t\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=u\n"
        "NEXTSEEK_PASSWORD=p\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    pytester.makeconftest(_CONFTEST_SRC)
    pytester.makepyfile(
        test_skipped_live=textwrap.dedent(
            """
            import pytest

            @pytest.mark.live
            def test_skips():
                pytest.skip("simulated skip")
            """
        )
    )
    result = pytester.runpytest("-v", "--no-cov", "-p", "no:cacheprovider")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*SESSION GUARD FAIL*no @pytest.mark.live tests actually ran*"])


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
