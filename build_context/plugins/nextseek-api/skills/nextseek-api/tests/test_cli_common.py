"""Unit tests for the shared CLI argparse helpers (Issue #6).

The `add_env_file_arg` helper centralizes --env-file registration so every
nextseek-* shim picks up identical behavior. These tests pin the contract:
  * --env-file PATH is registered
  * the default is None (optional everywhere)
  * the parsed value is a pathlib.Path (for args.env_file.expanduser() use)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lib.cli_common import add_env_file_arg, add_env_flag


def test_add_env_file_arg_registers_flag() -> None:
    parser = argparse.ArgumentParser()
    add_env_file_arg(parser)
    ns = parser.parse_args(["--env-file", "/tmp/x"])
    assert ns.env_file == Path("/tmp/x")


def test_add_env_file_arg_default_none() -> None:
    parser = argparse.ArgumentParser()
    add_env_file_arg(parser)
    ns = parser.parse_args([])
    assert ns.env_file is None


def test_add_env_file_arg_dest_is_env_file() -> None:
    """The destination attribute must be `env_file` (underscore, not dash)."""
    parser = argparse.ArgumentParser()
    add_env_file_arg(parser)
    ns = parser.parse_args(["--env-file", "/tmp/y"])
    assert hasattr(ns, "env_file")
    assert isinstance(ns.env_file, Path)


def test_add_env_file_arg_type_is_path() -> None:
    """Parsed value must be a Path so callers can call .expanduser() safely."""
    parser = argparse.ArgumentParser()
    add_env_file_arg(parser)
    ns = parser.parse_args(["--env-file", "~/secrets/.env"])
    # Path("~/...") is preserved verbatim (expansion happens later).
    assert isinstance(ns.env_file, Path)
    assert ns.env_file == Path("~/secrets/.env")


def test_add_env_flag_registers_choices() -> None:
    parser = argparse.ArgumentParser()
    add_env_flag(parser)
    ns = parser.parse_args(["--env", "dev"])
    assert ns.env == "dev"


def test_add_env_flag_default_is_prod() -> None:
    parser = argparse.ArgumentParser()
    add_env_flag(parser)
    ns = parser.parse_args([])
    assert ns.env == "prod"


def test_add_env_flag_rejects_invalid_choice() -> None:
    parser = argparse.ArgumentParser()
    add_env_flag(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--env", "staging"])
