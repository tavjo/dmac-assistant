"""Contract tests for build_tools.verify_env."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from build_tools.verify_env import REQUIRED_VARS, validate_env


CANARY = "LITERAL-CANARY-TOKEN-VALUE"


def _good_env() -> dict[str, str]:
    return {
        "AWS_BEARER_TOKEN_BEDROCK": "bedrock-token-xyz",
        "AWS_REGION": "us-east-1",
        "NEXTSEEK_USERNAME": "alice",
        "NEXTSEEK_PASSWORD": "s3cret",
        "NEXTSEEK_URL": "https://nextseek-dev.example.mit.edu",
        "GCP_API_KEY": "gcp-fake-key",
    }


def test_required_vars_constant_exact() -> None:
    assert REQUIRED_VARS == [
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "NEXTSEEK_USERNAME",
        "NEXTSEEK_PASSWORD",
        "NEXTSEEK_URL",
        "GCP_API_KEY",
    ]


def test_happy_path_returns_no_errors() -> None:
    assert validate_env(_good_env()) == []


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_missing_var_reports_that_var_by_name(missing_var: str) -> None:
    env = _good_env()
    del env[missing_var]
    errors = validate_env(env)
    assert len(errors) == 1
    assert missing_var in errors[0]
    assert "missing" in errors[0].lower()


@pytest.mark.parametrize("var", REQUIRED_VARS)
def test_empty_var_is_error(var: str) -> None:
    env = _good_env()
    env[var] = ""
    errors = validate_env(env)
    assert any(var in err for err in errors)


@pytest.mark.parametrize("var", REQUIRED_VARS)
def test_whitespace_only_var_is_error(var: str) -> None:
    env = _good_env()
    env[var] = "   \t\n"
    errors = validate_env(env)
    assert any(var in err for err in errors)


def test_bom_prefixed_value_is_error() -> None:
    env = _good_env()
    env["NEXTSEEK_USERNAME"] = "\ufeffalice"
    errors = validate_env(env)
    assert any("NEXTSEEK_USERNAME" in err and "BOM" in err for err in errors)


def test_trailing_whitespace_is_stripped_not_rejected() -> None:
    env = _good_env()
    env["NEXTSEEK_USERNAME"] = "alice   "
    assert validate_env(env) == []


def test_leading_whitespace_is_stripped_not_rejected() -> None:
    env = _good_env()
    env["NEXTSEEK_USERNAME"] = "   alice"
    assert validate_env(env) == []


@pytest.mark.parametrize(
    "bad_region", ["us-fake-99", "US-EAST-1", "eastus", "", "us_east_1"]
)
def test_wrong_region_is_error(bad_region: str) -> None:
    env = _good_env()
    env["AWS_REGION"] = bad_region
    errors = validate_env(env)
    assert any("AWS_REGION" in err for err in errors)


@pytest.mark.parametrize(
    "good_region", ["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"]
)
def test_good_region_accepted(good_region: str) -> None:
    env = _good_env()
    env["AWS_REGION"] = good_region
    assert validate_env(env) == []


def test_non_dev_nextseek_url_is_error() -> None:
    env = _good_env()
    env["NEXTSEEK_URL"] = "https://nextseek-prod.example.mit.edu"
    errors = validate_env(env)
    assert any("NEXTSEEK_URL" in err and "dev" in err for err in errors)


def test_http_nextseek_url_is_error() -> None:
    env = _good_env()
    env["NEXTSEEK_URL"] = "http://nextseek-dev.example.mit.edu"
    errors = validate_env(env)
    assert any("NEXTSEEK_URL" in err and "https" in err.lower() for err in errors)


@pytest.mark.parametrize(
    "dev_url",
    [
        "https://dev.nextseek.mit.edu",
        "https://nextseek-dev.mit.edu",
        "https://dev-api.nextseek.mit.edu",
    ],
)
def test_dev_gate_accepts_real_dev_hosts(dev_url: str) -> None:
    env = _good_env()
    env["NEXTSEEK_URL"] = dev_url
    assert validate_env(env) == []


@pytest.mark.parametrize(
    "gameable_url",
    [
        "https://devops.example.mit.edu",
        "https://developer.prod.mit.edu",
        "https://nextseek.mit.edu/dev-test/",
        "https://development.example.com",
        "https://nextseek-development.mit.edu",
    ],
)
def test_dev_gate_rejects_substring_gameability(gameable_url: str) -> None:
    env = _good_env()
    env["NEXTSEEK_URL"] = gameable_url
    errors = validate_env(env)
    assert any("NEXTSEEK_URL" in err and "dev" in err for err in errors)


def test_canary_secret_value_never_echoed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = _good_env()
    env["AWS_BEARER_TOKEN_BEDROCK"] = CANARY
    env["AWS_REGION"] = "us-fake-99"
    errors = validate_env(env)
    for err in errors:
        assert CANARY not in err, f"error leaked canary: {err!r}"

    from build_tools.verify_env.__main__ import main

    rc = main(["--check"], env_override=env)
    captured = capsys.readouterr()
    assert rc == 1
    assert CANARY not in captured.out
    assert CANARY not in captured.err


def test_cli_exit_0_on_happy_path(capsys: pytest.CaptureFixture[str]) -> None:
    from build_tools.verify_env.__main__ import main

    rc = main(["--check"], env_override=_good_env())
    captured = capsys.readouterr()
    assert rc == 0
    assert "all required vars present" in captured.out


def test_cli_exit_1_on_any_error(capsys: pytest.CaptureFixture[str]) -> None:
    from build_tools.verify_env.__main__ import main

    env = _good_env()
    del env["NEXTSEEK_URL"]
    rc = main(["--check"], env_override=env)
    captured = capsys.readouterr()
    assert rc == 1
    assert "NEXTSEEK_URL" in captured.err


def test_cli_via_subprocess_happy_path(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AWS_BEARER_TOKEN_BEDROCK=bedrock-token-xyz\n"
        "AWS_REGION=us-east-1\n"
        "NEXTSEEK_USERNAME=alice\n"
        "NEXTSEEK_PASSWORD=s3cret\n"
        "NEXTSEEK_URL=https://nextseek-dev.example.mit.edu\n"
        "GCP_API_KEY=gcp-fake-key\n",
        encoding="utf-8",
    )
    child_env = {k: v for k, v in os.environ.items() if k not in REQUIRED_VARS}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build_tools.verify_env",
            "--check",
            "--env-file",
            str(env_file),
        ],
        capture_output=True,
        text=True,
        env=child_env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cli_via_subprocess_missing_vars(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AWS_REGION=us-east-1\n", encoding="utf-8")
    child_env = {k: v for k, v in os.environ.items() if k not in REQUIRED_VARS}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build_tools.verify_env",
            "--check",
            "--env-file",
            str(env_file),
        ],
        capture_output=True,
        text=True,
        env=child_env,
        check=False,
    )
    assert result.returncode == 1
    assert "AWS_BEARER_TOKEN_BEDROCK" in result.stderr
