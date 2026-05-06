"""Unit tests for build_tools.verify_env (validate_env + CLI)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from build_tools.verify_env import REQUIRED_VARS, validate_env
from build_tools.verify_env import __main__ as cli


VALID_ENV = {
    "AWS_BEARER_TOKEN_BEDROCK": "tok-abc",
    "AWS_REGION": "us-east-1",
    "NEXTSEEK_USERNAME": "alice",
    "NEXTSEEK_PASSWORD": "s3cret",
    "NEXTSEEK_URL": "https://dev.nextseek.example.com/api",
    "GCP_API_KEY": "gcp-fake-key",
}


# ---- validate_env ---------------------------------------------------------


def test_validate_env_accepts_valid_env() -> None:
    assert validate_env(VALID_ENV) == []


def test_validate_env_reports_missing_vars() -> None:
    errors = validate_env({})
    assert len(errors) >= len(REQUIRED_VARS)
    for var in REQUIRED_VARS:
        assert any(var in e and "missing" in e for e in errors)


def test_validate_env_rejects_bom_prefix() -> None:
    env = {**VALID_ENV, "AWS_REGION": "﻿us-east-1"}
    errors = validate_env(env)
    assert any("BOM" in e and "AWS_REGION" in e for e in errors)


def test_validate_env_rejects_empty_or_whitespace_value() -> None:
    env = {**VALID_ENV, "NEXTSEEK_USERNAME": "   "}
    errors = validate_env(env)
    assert any("NEXTSEEK_USERNAME" in e and "empty" in e for e in errors)


def test_validate_env_rejects_malformed_aws_region() -> None:
    env = {**VALID_ENV, "AWS_REGION": "not-a-region"}
    errors = validate_env(env)
    assert any("AWS_REGION" in e and "shape" in e for e in errors)


def test_validate_env_does_not_check_region_shape_when_missing() -> None:
    env = {k: v for k, v in VALID_ENV.items() if k != "AWS_REGION"}
    errors = validate_env(env)
    # Only the "missing" error for AWS_REGION, no shape error
    region_errors = [e for e in errors if e.startswith("AWS_REGION")]
    assert len(region_errors) == 1
    assert "missing" in region_errors[0]


def test_validate_env_rejects_non_https_url() -> None:
    env = {**VALID_ENV, "NEXTSEEK_URL": "http://dev.example.com/api"}
    errors = validate_env(env)
    assert any("NEXTSEEK_URL" in e and "https" in e for e in errors)


def test_validate_env_rejects_prod_url() -> None:
    env = {**VALID_ENV, "NEXTSEEK_URL": "https://prod.example.com/api"}
    errors = validate_env(env)
    assert any("NEXTSEEK_URL" in e and "dev" in e for e in errors)


def test_validate_env_accepts_dev_dash_prefix_host() -> None:
    env = {**VALID_ENV, "NEXTSEEK_URL": "https://dev-app.example.com/api"}
    assert validate_env(env) == []


def test_validate_env_accepts_dash_dev_suffix_host() -> None:
    env = {**VALID_ENV, "NEXTSEEK_URL": "https://app-dev.example.com/api"}
    assert validate_env(env) == []


def test_validate_env_strips_surrounding_whitespace_for_url_check() -> None:
    env = {**VALID_ENV, "NEXTSEEK_URL": "  https://dev.example.com/api  "}
    assert validate_env(env) == []


def test_validate_env_does_not_url_check_when_missing() -> None:
    env = {k: v for k, v in VALID_ENV.items() if k != "NEXTSEEK_URL"}
    errors = validate_env(env)
    url_errors = [e for e in errors if e.startswith("NEXTSEEK_URL")]
    assert len(url_errors) == 1
    assert "missing" in url_errors[0]


def test_validate_env_never_leaks_secret_values() -> None:
    env = {**VALID_ENV, "AWS_BEARER_TOKEN_BEDROCK": "﻿-supersecret"}
    errors = validate_env(env)
    joined = "\n".join(errors)
    assert "supersecret" not in joined


# ---- _load_env_file -------------------------------------------------------


def test_load_env_file_returns_empty_when_missing(tmp_path: Path) -> None:
    assert cli._load_env_file(tmp_path / "nope.env") == {}


def test_load_env_file_parses_basic_lines(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# comment line\n"
        "\n"
        "FOO=bar\n"
        'QUOTED="hello world"\n'
        "SINGLE='abc'\n"
        "MALFORMED_NO_EQUALS\n"
        "  KEY  =  value  \n"
    )
    out = cli._load_env_file(p)
    assert out == {
        "FOO": "bar",
        "QUOTED": "hello world",
        "SINGLE": "abc",
        "KEY": "value",
    }


# ---- main CLI ------------------------------------------------------------


def test_main_returns_0_when_env_override_valid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main(["--check"], env_override=VALID_ENV)
    assert rc == 0
    captured = capsys.readouterr()
    assert "all required vars present" in captured.out


def test_main_returns_0_silent_without_check_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main([], env_override=VALID_ENV)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_returns_1_and_prints_errors_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main(["--check"], env_override={})
    assert rc == 1
    captured = capsys.readouterr()
    assert "missing" in captured.err


def test_main_uses_os_environ_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    rc = cli.main([])
    assert rc == 0


def test_main_loads_env_file_but_real_env_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Clear any pre-existing values so the env-file is the source.
    for k in REQUIRED_VARS:
        monkeypatch.delenv(k, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in VALID_ENV.items()) + "\n"
    )
    rc = cli.main(["--check", "--env-file", str(env_file)])
    assert rc == 0


def test_main_real_env_overrides_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # File has a bad region; real env has a good region — real env wins.
    for k in REQUIRED_VARS:
        monkeypatch.delenv(k, raising=False)
    env_file = tmp_path / ".env"
    bad = {**VALID_ENV, "AWS_REGION": "garbage"}
    env_file.write_text("\n".join(f"{k}={v}" for k, v in bad.items()) + "\n")
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    rc = cli.main(["--check", "--env-file", str(env_file)])
    assert rc == 0


def test_main_module_dunder_executes_via_runpy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the ``if __name__ == '__main__'`` guard via runpy."""
    import runpy

    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("sys.argv", ["verify_env"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("build_tools.verify_env", run_name="__main__")
    assert exc_info.value.code == 0
