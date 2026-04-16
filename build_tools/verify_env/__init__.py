"""Validate the five bridge-side live E2E environment variables.

DD-19 keeps these names aligned with CLAUDE.md's bridge-side contract:
NEXTSEEK credentials enter as NEXTSEEK_USERNAME/NEXTSEEK_PASSWORD/NEXTSEEK_URL,
and T02's entrypoint aliases them to the plugin's canonical names before exec.
"""
from __future__ import annotations

import re
from typing import Mapping
from urllib.parse import urlparse


REQUIRED_VARS: list[str] = [
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "NEXTSEEK_USERNAME",
    "NEXTSEEK_PASSWORD",
    "NEXTSEEK_URL",
]

_AWS_REGION_RE = re.compile(
    r"^[a-z]{2}-(?:central|north|south|east|west|"
    r"northeast|northwest|southeast|southwest)(?:-[a-z]+)?-\d+$"
)
_BOM = "\ufeff"


def _is_dev_url(url: str) -> bool:
    """Accept only concrete dev-style host segments, not loose substrings."""
    host = urlparse(url).hostname or ""
    segments = host.split(".")
    return any(
        segment == "dev"
        or segment.startswith("dev-")
        or segment.endswith("-dev")
        for segment in segments
    )


def validate_env(env: Mapping[str, str]) -> list[str]:
    """Return validation errors using variable names only, never secret values."""
    errors: list[str] = []
    trimmed: dict[str, str] = {}

    for var in REQUIRED_VARS:
        raw = env.get(var)
        if raw is None:
            errors.append(f"{var}: missing from environment")
            continue
        if raw.startswith(_BOM):
            errors.append(
                f"{var}: value starts with a BOM character; re-save .env as UTF-8 without BOM"
            )
            continue

        value = raw.strip()
        if value == "":
            errors.append(f"{var}: empty or whitespace-only")
            continue
        trimmed[var] = value

    region = trimmed.get("AWS_REGION")
    if region is not None and not _AWS_REGION_RE.match(region):
        errors.append(
            "AWS_REGION: does not match expected shape <geo>-<dir>-<n> "
            "(e.g. us-east-1)"
        )

    url = trimmed.get("NEXTSEEK_URL")
    if url is not None:
        if not url.startswith("https://"):
            errors.append("NEXTSEEK_URL: must use https scheme")
        elif not _is_dev_url(url):
            errors.append(
                "NEXTSEEK_URL: hostname must contain a 'dev' segment "
                "(exactly 'dev', 'dev-*', or '*-dev'); refusing to run live "
                "E2E against prod (DD-21)"
            )

    return errors
