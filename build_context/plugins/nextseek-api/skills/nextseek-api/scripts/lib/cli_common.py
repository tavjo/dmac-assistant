"""Shared argparse helpers for all nextseek-* CLIs.

Centralizing flag registration here prevents drift between shims (Issue #6).
Every shim that needs `--env-file PATH` must register it via
`add_env_file_arg(parser)` so the type, metavar, help text, and default stay
identical across shims.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def add_env_file_arg(parser: argparse.ArgumentParser) -> None:
    """Register --env-file PATH with a consistent help string and default=None.

    The flag is optional across every shim. When omitted, callers should fall
    back to the current behavior (os.environ + default `.env` discovery).

    Callers should pass `args.env_file` directly to
    `env_loader.load_environment()`. `type=Path` matches existing expectations
    like `args.env_file.expanduser()`.
    """
    parser.add_argument(
        "--env-file",
        dest="env_file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a .env file (optional). Falls back to os.environ if omitted.",
    )


def add_env_flag(parser: argparse.ArgumentParser) -> None:
    """Register --env {prod,dev} used by init and session shims."""
    parser.add_argument(
        "--env",
        choices=["prod", "dev"],
        default="prod",
        help="Which environment to target (default: prod).",
    )
