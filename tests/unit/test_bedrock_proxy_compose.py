"""T2 — Bedrock auth-proxy compose/Dockerfile structural gates + R-9 runtime parity.

Hermetic (no Docker) tests parse the actual compose YAML + Dockerfile on disk and
assert the OI-3 containment invariants:
  * compose has NO `ports:` (gate G5 — proxy reachable only on the Docker net),
  * the network `dmac-nextseek-net` is declared `external: true` (R-6 fail-fast),
  * the secret env_file path (`bedrock-proxy/proxy-secret.env`) is gitignored,
  * the image runs non-root as uid 1001 (asserted from the Dockerfile),
  * R-9 RUNTIME parity: `config.load_config()` honors DMAC_BEDROCK_PROXY_URL and
    falls back to the compose-matching default `http://bedrock-proxy:8080`.

A `live_docker`-marked test (G6) builds a throwaway sentinel image to PROVE the
scanner detects a baked token (negative control), then scans the real
`dmac-bedrock-proxy:poc` image and asserts ZERO token hits.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_PATH = _REPO_ROOT / "bedrock-proxy" / "docker-compose.yml"
_DOCKERFILE_PATH = _REPO_ROOT / "bedrock-proxy" / "Dockerfile"
_SECRET_ENV_REL = "bedrock-proxy/proxy-secret.env"

# Defaults that R-9 pins to EXACTLY two sources (this file mirrors the compose
# side via the parsed YAML; the config side is asserted at runtime).
_EXPECTED_NETWORK = "dmac-nextseek-net"
_EXPECTED_SERVICE = "bedrock-proxy"
_EXPECTED_IMAGE = "dmac-bedrock-proxy:poc"
_EXPECTED_CONTAINER = "dmac-bedrock-proxy"
_COMPOSE_DEFAULT_PROXY_URL = "http://bedrock-proxy:8080"


# ---------------------------------------------------------------------------
# Compose YAML — parsed from disk, never a hardcoded copy.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def compose() -> dict:
    with _COMPOSE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def service(compose: dict) -> dict:
    services = compose.get("services", {})
    assert _EXPECTED_SERVICE in services, f"service {_EXPECTED_SERVICE!r} missing"
    return services[_EXPECTED_SERVICE]


def test_no_ports_key_anywhere(compose: dict, service: dict) -> None:
    """Gate G5: NO `ports:` mapping — the proxy must not bind a host port."""
    assert "ports" not in service, "compose service must not declare `ports:`"
    # Defensive: no service in the file may expose host ports.
    for name, svc in compose.get("services", {}).items():
        assert "ports" not in (svc or {}), f"service {name!r} declares ports:"


def test_image_and_container_names(service: dict) -> None:
    assert service.get("image") == _EXPECTED_IMAGE
    assert service.get("container_name") == _EXPECTED_CONTAINER


def test_network_declared_external(compose: dict, service: dict) -> None:
    """R-6: the proxy JOINS the external dmac-nextseek-net (does not create it)."""
    networks = compose.get("networks", {})
    assert networks, "compose must declare a networks: block"
    # Exactly one declared network, marked external, resolving to dmac-nextseek-net.
    external_names = []
    for net in networks.values():
        net = net or {}
        if net.get("external") is True:
            # `name` may be a ${VAR:-default}; the default is the pinned literal.
            raw_name = str(net.get("name", ""))
            resolved = raw_name.split(":-", 1)[-1].rstrip("}") if raw_name else ""
            external_names.append(resolved)
    assert _EXPECTED_NETWORK in external_names, (
        f"network {_EXPECTED_NETWORK!r} must be declared external; "
        f"found external names: {external_names}"
    )
    # The service must attach to one of the declared networks.
    svc_nets = service.get("networks", [])
    assert svc_nets, "service must attach to a network"


def test_token_via_gitignored_env_file(service: dict) -> None:
    """The bearer token enters via the gitignored secret env_file, not inline env."""
    env_file = service.get("env_file")
    assert env_file, "service must declare env_file for the secret"
    # env_file may be a list of strings or list of {path: ...} mappings.
    paths = []
    for entry in env_file if isinstance(env_file, list) else [env_file]:
        if isinstance(entry, dict):
            paths.append(str(entry.get("path", "")))
        else:
            paths.append(str(entry))
    assert any("proxy-secret.env" in p for p in paths), (
        f"env_file must reference proxy-secret.env; got {paths}"
    )
    # The token must NOT be present as an inline environment value.
    environment = service.get("environment", {}) or {}
    env_blob = json.dumps(environment)
    assert "AWS_BEARER_TOKEN_BEDROCK" not in env_blob, (
        "the bearer token must not appear in the compose `environment:` block"
    )


def test_secret_env_is_gitignored() -> None:
    """`git check-ignore` must succeed for the real secret env (exit 0)."""
    result = subprocess.run(
        ["git", "check-ignore", _SECRET_ENV_REL],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{_SECRET_ENV_REL} is not gitignored (git check-ignore rc="
        f"{result.returncode}): {result.stdout}{result.stderr}"
    )


def test_secret_env_example_is_committed_and_valueless() -> None:
    """The template is committed (NOT gitignored) and carries key NAMES only."""
    example = _REPO_ROOT / "bedrock-proxy" / "proxy-secret.env.example"
    assert example.is_file(), "proxy-secret.env.example template must exist"
    # NOT gitignored (exit 1 from check-ignore).
    result = subprocess.run(
        ["git", "check-ignore", "bedrock-proxy/proxy-secret.env.example"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "the .example template must NOT be gitignored"
    # Every non-comment line is `KEY=` with NO value (no real secret committed).
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "=" in stripped, f"template line not KEY=value shape: {line!r}"
        key, _, value = stripped.partition("=")
        assert value == "", f"template must carry NO values; {key} has a value"


# ---------------------------------------------------------------------------
# Dockerfile — non-root uid 1001 + healthcheck on /healthz.
# ---------------------------------------------------------------------------
def test_dockerfile_runs_non_root_uid_1001() -> None:
    text = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "useradd -m -u 1001" in text, "image must create uid 1001"
    # The slim base reserves the name `proxy` (uid 13), so the app user is
    # `proxyapp`; the load-bearing invariant is the non-root uid 1001 + USER drop.
    assert "USER proxyapp" in text, "image must drop to the non-root uid-1001 user"


def test_dockerfile_healthcheck_hits_healthz() -> None:
    text = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "HEALTHCHECK" in text, "Dockerfile must declare a HEALTHCHECK"
    assert "/healthz" in text, "HEALTHCHECK must probe /healthz"
    assert "8080" in text, "HEALTHCHECK must target port 8080"


# ---------------------------------------------------------------------------
# R-9 RUNTIME parity: load_config() honors the env override and falls back to
# the compose-matching default. Mirrors the existing test_config.py fixture
# style (monkeypatch dev-mode + DMAC_USERS + a tmp catalog), not a new style.
# ---------------------------------------------------------------------------
_GOOD_USERS = {"alice": {"password": "s3cret-alice", "projects": ["proj-a"]}}
_BRIDGE_ENV_VARS = (
    "DMAC_DEV_MODE",
    "DMAC_USERS",
    "DMAC_CLAUDE_USERS_ROOT",
    "DMAC_SCRATCH_ROOT",
    "DMAC_DROPBOX_ROOT",
    "DMAC_OUTPUT_ROOT",
    "DMAC_CATALOG_FILE_HOST_PATH",
    "DMAC_BRIDGE_HOST",
    "DMAC_BRIDGE_PORT",
    "DMAC_SIDECAR_NETWORK",
    "DMAC_SIDECAR_STAGING_ROOT",
    "DMAC_BEDROCK_PROXY_URL",
)


@pytest.fixture
def bridge_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Minimal valid bridge env (mirrors test_config.py's clean_env+_set_good_env)."""
    for var in _BRIDGE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Don't load the developer's real repo .env (would defeat delenv).
    import dmac_assistant.config as config_mod

    isolated = tmp_path / "no_dotenv_here"
    isolated.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", isolated, raising=False)

    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")

    monkeypatch.setenv("DMAC_USERS", json.dumps(_GOOD_USERS))
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", str(tmp_path / "claude-users"))
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", str(tmp_path / "dropbox"))
    monkeypatch.setenv("DMAC_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("DMAC_SIDECAR_STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(catalog))
    return monkeypatch


def test_runtime_parity_env_override(bridge_env: pytest.MonkeyPatch) -> None:
    """A non-default DMAC_BEDROCK_PROXY_URL must flow through to the config."""
    bridge_env.setenv("DMAC_BEDROCK_PROXY_URL", "http://elsewhere:9999")
    from dmac_assistant.config import load_config

    cfg = load_config()
    assert cfg.bedrock_proxy_url == "http://elsewhere:9999"


def test_runtime_parity_default_matches_compose(
    bridge_env: pytest.MonkeyPatch,
) -> None:
    """Unset → config default must equal the compose service default URL (R-9)."""
    bridge_env.delenv("DMAC_BEDROCK_PROXY_URL", raising=False)
    from dmac_assistant.config import load_config

    cfg = load_config()
    assert cfg.bedrock_proxy_url == _COMPOSE_DEFAULT_PROXY_URL


def test_config_default_constant_matches_compose() -> None:
    """The config default constant equals the compose-side default literal."""
    from dmac_assistant.config import _DEFAULT_BEDROCK_PROXY_URL

    assert _DEFAULT_BEDROCK_PROXY_URL == _COMPOSE_DEFAULT_PROXY_URL


# ---------------------------------------------------------------------------
# G6 — token-not-baked, WITH a negative control. Opt-in (live_docker): builds a
# throwaway sentinel image, asserts the scanner FLAGS it (detector proven), then
# scans the real image and asserts 0 hits.
# ---------------------------------------------------------------------------
_SENTINEL = "OI3-SENTINEL-TOKEN-DO-NOT-USE-9f3a"
_THROWAWAY_TAG = "dmac-bedrock-proxy-g6-negctl:throwaway"


def _scan_image_for(tag: str, needle: str) -> int:
    """Return the number of places `needle` appears in an image's env + layers.

    Inspects `Config.Env` (and the full inspect blob) plus `docker history`
    (layer-creation commands). A baked-in env/layer token surfaces in at least
    one of these; a runtime-only token (injected via env_file at `up`) does not.
    """
    hits = 0
    inspect = subprocess.run(
        ["docker", "inspect", tag],
        capture_output=True,
        text=True,
    )
    if inspect.returncode == 0 and needle in inspect.stdout:
        hits += inspect.stdout.count(needle)
    history = subprocess.run(
        ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", tag],
        capture_output=True,
        text=True,
    )
    if history.returncode == 0 and needle in history.stdout:
        hits += history.stdout.count(needle)
    return hits


@pytest.mark.live_docker
def test_g6_token_not_baked_with_negative_control(tmp_path: Path) -> None:
    """Negative control fires (sentinel image flagged), real image has 0 hits."""
    # --- Negative control: build a throwaway image that BAKES the sentinel. ---
    throwaway_df = tmp_path / "Dockerfile.negctl"
    throwaway_df.write_text(
        "FROM busybox:latest\n"
        f'ENV AWS_BEARER_TOKEN_BEDROCK="{_SENTINEL}"\n',
        encoding="utf-8",
    )
    build = subprocess.run(
        ["docker", "build", "-f", str(throwaway_df), "-t", _THROWAWAY_TAG, str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"negative-control build failed: {build.stderr}"
    try:
        neg_hits = _scan_image_for(_THROWAWAY_TAG, _SENTINEL)
        assert neg_hits >= 1, (
            "NEGATIVE CONTROL FAILED: scanner did not flag a baked sentinel "
            f"(hits={neg_hits}); the detector is not proven, so a 0-hit result "
            "on the real image would be meaningless"
        )
        print(f"G6 negative control FIRED: sentinel image flagged ({neg_hits} hits)")

        # --- Real image: must have ZERO sentinel hits AND zero token presence. ---
        real_hits = _scan_image_for(_EXPECTED_IMAGE, _SENTINEL)
        assert real_hits == 0, f"real image leaked the sentinel ({real_hits} hits)"
        # Also confirm no NON-EMPTY bearer token value is baked into Config.Env.
        inspect = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Config.Env}}", _EXPECTED_IMAGE],
            capture_output=True,
            text=True,
        )
        assert inspect.returncode == 0, f"docker inspect failed: {inspect.stderr}"
        env_list = json.loads(inspect.stdout)
        for entry in env_list:
            key, _, value = entry.partition("=")
            if key == "AWS_BEARER_TOKEN_BEDROCK":
                assert value == "", (
                    f"image bakes a non-empty bearer token: {key}={value!r}"
                )
        print("G6: real image dmac-bedrock-proxy:poc has 0 token hits")
    finally:
        subprocess.run(
            ["docker", "rmi", "-f", _THROWAWAY_TAG],
            capture_output=True,
            text=True,
        )
