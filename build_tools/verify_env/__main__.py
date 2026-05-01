"""CLI entry point for env validation."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping

from build_tools.verify_env import validate_env


def _load_env_file(path: Path) -> dict[str, str]:
    """Load a minimal KEY=VALUE env file without shell expansion."""
    result: dict[str, str] = {}
    if not path.exists():
        return result

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def main(
    argv: list[str] | None = None,
    *,
    env_override: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_env",
        description="Validate DMAC live E2E env vars.",
    )
    parser.add_argument("--check", action="store_true", help="run validation and exit 0/1")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="load vars from a .env file (optional)",
    )
    args = parser.parse_args(argv)

    if env_override is not None:
        env: dict[str, str] = dict(env_override)
    else:
        env = dict(os.environ)
        if args.env_file is not None:
            env = {**_load_env_file(args.env_file), **env}

    errors = validate_env(env)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.check:
        print("verify_env: all required vars present and shape-valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
