"""Environment / credential loader for the nextseek-api plugin.

Single source of truth for converting a `.env` file (or raw os.environ)
into a validated NextseekConfig. Supports BOTH canonical and legacy
env var names so the plugin works with existing BMC .env files.

Ported and simplified from T2Viz's orchestration/preflight.py
(load_runtime_environment at lines 48-73), with changes:
- Returns a NextseekConfig directly instead of a dict
- Raises EnvMissingError for missing file or missing creds
- Adds explicit DEFAULT_PROD_BASE_URL / DEFAULT_DEV_BASE_URL constants
- Separate prompt_for_env_interactive() helper for CLI bootstrap

Env var precedence (DD-07):
  base_url: NEXTSEEK_BASE_URL > API_BASE_URL > BASE_URL > default
  user:     SEEK_USER > username
  pass:     SEEK_PASSWORD > password

USE_DEV_API=truthy forces base_url to the dev variant even if
NEXTSEEK_BASE_URL is set to a prod URL (matches T2Viz preflight.py:61-66).
"""

from __future__ import annotations

from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values

from lib.nextseek_client import NextseekConfig


# Canonical defaults — these are the hardcoded fallbacks used when no
# env var of any kind provides a base URL.
DEFAULT_PROD_BASE_URL = "https://nextseek.mit.edu/nextseek_api"
DEFAULT_DEV_BASE_URL = "https://nextseek-dev.mit.edu/nextseek_api"

_TRUTHY_VALUES = {"1", "true", "yes", "on"}

# Markers for detect_env_mismatch. dev marker must be checked first because
# "nextseek.mit.edu" is a substring of "nextseek-dev.mit.edu".
_PROD_HOST_MARKERS = ("nextseek.mit.edu",)
_DEV_HOST_MARKERS = ("nextseek-dev.mit.edu",)
_API_SUFFIX = "/nextseek_api"


def _canonicalize_base_url(url: str) -> str:
    """Normalize a base URL so it always ends in exactly one ``/nextseek_api``.

    Handles inputs with or without the suffix and strips trailing slashes.
    """
    url = url.strip().rstrip("/")
    if url.endswith(_API_SUFFIX):
        return url
    return url + _API_SUFFIX


def canonicalize_endpoint(path: str) -> str:
    """Strip a leading ``/`` and a leading ``nextseek_api/`` from an endpoint path.

    The NExtSEEK client dispatches relative to a base URL that already ends
    in ``/nextseek_api``, so endpoint paths must not repeat that prefix.
    """
    p = path.strip()
    if p.startswith("/"):
        p = p[1:]
    if p.startswith("nextseek_api/"):
        p = p[len("nextseek_api/"):]
    return p


def resolve_base_url(
    file_env: dict[str, str],
    *,
    use_dev: bool | None = None,
) -> tuple[str, str]:
    """Resolve the canonical base URL and report which source won.

    Precedence (highest first):
        1. ``USE_DEV_API`` (hard override) -> BASE_URL_DEV or DEFAULT_DEV
        2. ``NEXTSEEK_BASE_URL``
        3. ``API_BASE_URL`` (legacy)
        4. ``BASE_URL`` (legacy)
        5. DEFAULT_DEV_BASE_URL if ``use_dev`` else DEFAULT_PROD_BASE_URL

    Returns:
        (canonical_url, source_name) where source_name is one of
        ``"USE_DEV_API"``, ``"NEXTSEEK_BASE_URL"``, ``"API_BASE_URL"``,
        ``"BASE_URL"``, or ``"default"``.
    """
    import os
    merged: dict[str, str] = {
        k: v for k, v in os.environ.items() if v is not None
    }
    merged.update(file_env)

    if _is_truthy(merged.get("USE_DEV_API")):
        raw = merged.get("BASE_URL_DEV") or DEFAULT_DEV_BASE_URL
        return _canonicalize_base_url(raw), "USE_DEV_API"

    for name in ("NEXTSEEK_BASE_URL", "API_BASE_URL", "BASE_URL"):
        value = merged.get(name)
        if value:
            return _canonicalize_base_url(value), name

    default = DEFAULT_DEV_BASE_URL if use_dev else DEFAULT_PROD_BASE_URL
    return _canonicalize_base_url(default), "default"


def detect_env_mismatch(base_url: str, selected_env: str) -> str:
    """Return one of ``"match"``, ``"prod-dev"``, ``"dev-prod"``, ``"unknown-host"``.

    - ``prod-dev``: URL host is prod but the user selected dev
    - ``dev-prod``: URL host is dev but the user selected prod
    - ``unknown-host``: URL matches neither known host
    - ``match``: URL host matches the selected environment
    """
    host = base_url.lower()
    # Check dev first because "nextseek.mit.edu" is a substring of
    # "nextseek-dev.mit.edu" — otherwise dev hosts would register as prod.
    is_dev = any(m in host for m in _DEV_HOST_MARKERS)
    is_prod = (
        any(m in host for m in _PROD_HOST_MARKERS) and not is_dev
    )
    if not (is_prod or is_dev):
        return "unknown-host"
    if is_prod and selected_env == "dev":
        return "prod-dev"
    if is_dev and selected_env == "prod":
        return "dev-prod"
    return "match"


class EnvMissingError(RuntimeError):
    """Raised when required environment / credentials cannot be loaded."""


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY_VALUES


def _read_env_file(env_path: Path | str | None) -> dict[str, str]:
    """Load a .env file into a dict[str, str], dropping None values.

    Raises EnvMissingError if env_path is given but doesn't exist.
    If env_path is None, returns an empty dict (caller falls back to
    os.environ).
    """
    if env_path is None:
        return {}

    path = Path(env_path)
    if not path.is_file():
        raise EnvMissingError(f"Env file not found: {path}")

    # dotenv_values returns dict[str, str | None]; we drop None entries
    raw = dotenv_values(path)
    return {k: v for k, v in raw.items() if v is not None}


def _lookup(env: dict[str, str], *names: str, default: str = "") -> str:
    """Return the first non-empty value found among `names`, else `default`."""
    for name in names:
        value = env.get(name)
        if value:
            return value
    return default


def load_environment(
    env_path: Path | str | None,
    *,
    use_dev: bool | None = None,
) -> NextseekConfig:
    """Load + normalize environment into a NextseekConfig.

    Args:
        env_path: Path to a .env file, or None to read only from os.environ.
            If a path is given and the file doesn't exist, raises EnvMissingError.
        use_dev: Optional explicit override for dev/prod default when no
            base URL env var is set. True -> dev default, False -> prod
            default, None -> prod default (safest for production work).

    Precedence (highest first):
        1. USE_DEV_API=truthy in env (forces dev URL, hard override)
        2. NEXTSEEK_BASE_URL env var
        3. API_BASE_URL env var (legacy)
        4. BASE_URL env var (legacy)
        5. DEFAULT_DEV_BASE_URL if use_dev=True; else DEFAULT_PROD_BASE_URL

    Credentials precedence:
        1. SEEK_USER / SEEK_PASSWORD (canonical)
        2. username / password (legacy)

    Raises:
        EnvMissingError: if env_path is given but missing, or if
            credentials cannot be resolved from any source.
    """
    # Layer 1: file values (may be empty dict)
    file_env = _read_env_file(env_path)

    # Layer 2: merge with os.environ for credential / tuning lookups.
    # Base-URL resolution is delegated to resolve_base_url() so there is a
    # single source of truth for URL precedence + canonicalization.
    import os
    merged: dict[str, str] = {
        k: v for k, v in os.environ.items() if v is not None
    }
    merged.update(file_env)

    base_url, base_url_source = resolve_base_url(file_env, use_dev=use_dev)

    # Credentials (canonical > legacy)
    username = _lookup(merged, "SEEK_USER", "username")
    password = _lookup(merged, "SEEK_PASSWORD", "password")

    if not username or not password:
        raise EnvMissingError(
            "Missing NExtSEEK credentials. Checked: "
            "SEEK_USER/SEEK_PASSWORD (canonical) and username/password (legacy). "
            f"Found user={'yes' if username else 'no'}, "
            f"pass={'yes' if password else 'no'}. "
            "Set them in your .env file or environment."
        )

    # Optional tuning knobs
    timeout_raw = merged.get("NEXTSEEK_CLIENT_TIMEOUT", "30.0")
    retries_raw = merged.get("NEXTSEEK_CLIENT_MAX_RETRIES", "3")

    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 30.0
    try:
        max_retries = int(retries_raw)
    except ValueError:
        max_retries = 3

    return NextseekConfig(
        base_url=base_url,
        username=username,
        password=password,
        timeout=timeout,
        max_retries=max_retries,
        base_url_source=base_url_source,
    )


def prompt_for_env_interactive() -> NextseekConfig:
    """Interactive fallback: prompt the user for base_url, user, password.

    Used by the CLI bootstrap when no .env file is available. Password is
    read via getpass() so it isn't echoed to the terminal. Covered 5%
    exception applies to the raw input() calls in tasks 07/10, not here;
    this function is directly unit-tested with mocked input.
    """
    base_url = input(
        "NExtSEEK base URL (e.g. https://nextseek.mit.edu/nextseek_api): "
    ).strip()
    if not base_url:
        base_url = DEFAULT_PROD_BASE_URL
    username = input("SEEK_USER: ").strip()
    password = getpass("SEEK_PASSWORD: ").strip()
    if not username or not password:
        raise EnvMissingError(
            "Interactive credential entry aborted: user and password required."
        )
    return NextseekConfig(
        base_url=base_url,
        username=username,
        password=password,
    )
