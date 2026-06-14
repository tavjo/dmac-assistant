"""Hermetic contract checks on sidecar/docker-compose.yml + Makefile + config parity.

Gate 15 (no host ports) + the R-7 one-config-source rule.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "sidecar" / "docker-compose.yml").read_text(encoding="utf-8")
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")


def test_no_host_ports_published():
    assert re.search(r"^\s*ports\s*:", COMPOSE, re.MULTILINE) is None, (
        "gate 15: the credential-holding sidecar must not publish host ports"
    )


def test_network_and_service_names_match_bridge_defaults():
    from dmac_assistant.config import _DEFAULT_SIDECAR_NETWORK

    assert f"name: ${{DMAC_SIDECAR_NETWORK:-{_DEFAULT_SIDECAR_NETWORK}}}" in COMPOSE
    assert "nextseek-sidecar:" in COMPOSE


def test_staging_bind_uses_env_var():
    assert "DMAC_SIDECAR_STAGING_ROOT" in COMPOSE


def test_local_overlay_env_file():
    """Amendment A-2 (2026-06-10): while the E2E target is the local NExtSEEK
    instance, the sidecar layers sidecar/local-nextseek.env (a gitignored copy
    of the stack's own nextseek.env) over ../.env so SESSION_DB_* and the
    shared-cred families point at the local stack without touching .env.
    The stack's nextseek.env interpolates $MYSQL_HOST/$NEXTSEEK_MYSQL_DATABASE
    from its sibling db.env, so BOTH are layered, in the stack's own order
    (db.env first). The overlays are optional (required: false) so sidecar-up
    keeps working after the files are deleted when the dev server returns."""
    comment_lines = r"(?:\s*#[^\n]*\n)*"
    assert re.search(
        r"env_file:\s*\n\s+- path: \.\./\.env\s*\n"
        + comment_lines
        + r"\s+- path: \./local-nextseek-db\.env\s*\n\s+required: false\s*\n"
        + comment_lines
        + r"\s+- path: \./local-nextseek\.env\s*\n\s+required: false\s*\n"
        + comment_lines
        + r"\s+- path: \./local-nextseek-dmac\.env\s*\n\s+required: false",
        COMPOSE,
    ), (
        "overlays must layer db.env, nextseek.env, then the dmac-vantage "
        "override file after ../.env, all optional"
    )
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "sidecar/local-nextseek*.env" in gitignore


def test_local_nextseek_network_attach():
    """Amendment A-1 (2026-06-10): the sidecar additionally joins the local
    NExtSEEK stack's network (`nextseek_default`, external) so sessions.py and
    the healthcheck can reach seek-mysql at db:3306. Agent containers do NOT
    join it — only the credential-holding sidecar."""
    assert re.search(r"^\s+- nextseek-local\s*$", COMPOSE, re.MULTILINE), (
        "service must list the nextseek-local network"
    )
    assert re.search(r"^\s+- dmac-net\s*$", COMPOSE, re.MULTILINE), (
        "service must still join the sidecar's own network"
    )
    assert re.search(
        r"nextseek-local:\s*\n\s+external: true\s*\n\s+name: nextseek_default",
        COMPOSE,
    ), "nextseek-local must map to the external nextseek_default network"


def test_no_internal_true():
    assert "internal: true" not in COMPOSE


def test_make_targets_exist():
    for target in ("sidecar-build:", "sidecar-up:", "sidecar-down:"):
        assert target in MAKEFILE
    assert "--wait" in MAKEFILE
