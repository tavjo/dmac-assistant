"""Cache directory resolution for the nextseek-api plugin.

Honors XDG_CACHE_HOME. All paths are env-scoped (dev vs prod) to prevent
cross-contamination.
"""

import os
from pathlib import Path


def resolve_plugin_cache_base() -> Path:
    """Return the base plugin cache dir: $XDG_CACHE_HOME/nextseek-api/ or ~/.cache/nextseek-api/.

    This is the BASE directory without env scoping. Callers that need env-scoped
    paths should use resolve_env_cache_dir().
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and xdg.strip():
        base = Path(xdg).expanduser()
    else:
        base = Path.home() / ".cache"
    return base / "nextseek-api" / "v2"


def resolve_env_cache_dir(env_tag: str) -> Path:
    """Return the env-scoped cache dir: ~/.cache/nextseek-api/{env_tag}/."""
    return resolve_plugin_cache_base() / env_tag


def resolve_session_json_path(env_tag: str) -> Path:
    """Return the path to session.json for the given env."""
    return resolve_env_cache_dir(env_tag) / "session.json"


def resolve_endpoints_minimal_path(env_tag: str) -> Path:
    """Return the path to endpoints_minimal.json for the given env."""
    return resolve_env_cache_dir(env_tag) / "endpoints_minimal.json"


def resolve_endpoints_full_dir(
    env_tag: str, *, cache_base: Path | None = None
) -> Path:
    """Return the directory containing per-operation full endpoint specs.

    If cache_base is provided (test hermeticity), it is used verbatim as the
    base instead of resolve_plugin_cache_base().
    """
    base = cache_base if cache_base is not None else resolve_plugin_cache_base()
    return base / env_tag / "endpoints_full"


def resolve_endpoint_full_path(
    env_tag: str, operation_id: str, *, cache_base: Path | None = None
) -> Path:
    """Return the path to a specific operation's full spec JSON.

    operation_id is sanitized: any ``/`` is replaced with ``_`` so exotic
    operation ids never escape the cache directory.
    """
    safe = operation_id.replace("/", "_")
    return resolve_endpoints_full_dir(env_tag, cache_base=cache_base) / f"{safe}.json"
