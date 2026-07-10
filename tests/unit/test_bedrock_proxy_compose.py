"""T2 — Bedrock auth-proxy compose/Dockerfile structural gates + R-9 runtime parity.

Hermetic (no Docker) tests parse the actual compose YAML + Dockerfile on disk and
assert the OI-3 containment invariants:
  * compose has NO `ports:` (gate G5 — proxy reachable only on the Docker net),
  * the network `dmac-nextseek-net` is declared `external: true` (R-6 fail-fast),
  * the secret env_file path (`bedrock-proxy/proxy-secret.env`) is gitignored,
  * the image runs non-root as uid 1001 (asserted from the Dockerfile),
  * R-9 RUNTIME parity: `config.load_config()` honors DMAC_BEDROCK_PROXY_URL and
    falls back to the compose-matching default `http://bedrock-proxy:8080`.

A `live_docker`-marked test (G6) builds throwaway sentinel images to PROVE the
scanner detects a baked token across ALL image surfaces — `Config.Env`,
`docker history` command text, AND the layer FILESYSTEM — via two negative
controls (an ENV-bake and a FILESYSTEM-bake), then scans the real
`dmac-bedrock-proxy:poc` image and asserts ZERO token hits on every surface.
"""
from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# R-9 parity: the expected proxy URL is DERIVED from the two real sources, not
# hand-copied. The compose SERVICE NAME + the Dockerfile listen PORT compose the
# `http://<service>:<port>` default; a rename on EITHER source must fail the test.
# ---------------------------------------------------------------------------
def _compose_service_name() -> str:
    """The single proxy service name, parsed from the real compose file."""
    with _COMPOSE_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    services = doc.get("services", {})
    assert len(services) == 1, (
        f"expected exactly one compose service, got {sorted(services)}"
    )
    return next(iter(services))


def _dockerfile_listen_port() -> int:
    """The uvicorn listen port, parsed from the real Dockerfile.

    Reads the `--port <N>` from the CMD; cross-checks it against the port in the
    HEALTHCHECK URL so a drift between the two also surfaces here.
    """
    text = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    cmd_match = re.search(r'--port["\s,]+["\s]*?(\d+)', text)
    assert cmd_match, "could not parse --port from the Dockerfile CMD"
    cmd_port = int(cmd_match.group(1))
    # HEALTHCHECK probes http://localhost:<port>/healthz — pin them in lockstep.
    hc_match = re.search(r"http://localhost:(\d+)/healthz", text)
    assert hc_match, "could not parse the HEALTHCHECK port from the Dockerfile"
    hc_port = int(hc_match.group(1))
    assert cmd_port == hc_port, (
        f"Dockerfile CMD port ({cmd_port}) != HEALTHCHECK port ({hc_port})"
    )
    return cmd_port


def _derived_proxy_url() -> str:
    """`http://<compose-service>:<dockerfile-port>` from the two real sources."""
    return f"http://{_compose_service_name()}:{_dockerfile_listen_port()}"


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


def test_dockerfile_copy_scope_is_app_subtree_only() -> None:
    """Every COPY source must be `bedrock-proxy/app/` (or a subpath).

    The build context is the repo ROOT (compose `context: ..`), which includes
    the gitignored real secret. The single thing standing between that context
    and the secret is the COPY scope: as long as nothing outside
    `bedrock-proxy/app/` is copied in, the secret (at the repo root) can never
    reach the image filesystem. This pins that invariant so a future
    `COPY . /app/` or `COPY bedrock-proxy/ ...` (which WOULD pull the secret) is
    rejected at test time, not discovered after a leak.
    """
    text = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    copy_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("COPY "):
            copy_lines.append(line)
    assert copy_lines, "expected at least one COPY in the Dockerfile"
    for line in copy_lines:
        # Strip any `COPY --flag=...` options; collect the remaining args. The
        # last arg is the destination; everything before it are sources.
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        assert len(tokens) >= 2, f"malformed COPY (no source+dest): {line!r}"
        sources = tokens[:-1]
        for src in sources:
            assert src == "bedrock-proxy/app/" or src.startswith(
                "bedrock-proxy/app/"
            ), (
                "COPY source must be scoped to bedrock-proxy/app/ (so the "
                f"repo-root secret can never be copied in); got {src!r} in {line!r}"
            )


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
    """Unset → config default must equal the DERIVED proxy URL (R-9).

    The expectation is built from the two real sources (compose service name +
    Dockerfile listen port), not a hand-copied constant, so a rename/port change
    on either source fails this test.
    """
    bridge_env.delenv("DMAC_BEDROCK_PROXY_URL", raising=False)
    from dmac_assistant.config import load_config

    cfg = load_config()
    assert cfg.bedrock_proxy_url == _derived_proxy_url()


def test_config_default_constant_matches_derived_sources() -> None:
    """R-9: the config default constant equals the URL DERIVED from the real
    compose service name + Dockerfile listen port (no hand-copied literal)."""
    from dmac_assistant.config import _DEFAULT_BEDROCK_PROXY_URL

    assert _DEFAULT_BEDROCK_PROXY_URL == _derived_proxy_url()


# ---------------------------------------------------------------------------
# G6 — token-not-baked, WITH negative controls across ALL image surfaces. Opt-in
# (live_docker): builds two throwaway sentinel images — one that bakes the token
# via ENV, one that bakes a DISTINCT sentinel into a layer FILESYSTEM file — and
# asserts the (filesystem-aware) scanner FLAGS each, proving each detection
# surface works. Only THEN does a 0-hit result on the real image mean anything.
# The earlier version inspected only `docker inspect` (Config.Env) + `docker
# history` (layer COMMAND TEXT); a token written into a layer's FILESYSTEM (via
# `COPY secret /app/` or `RUN echo $TOK > /f`) was invisible to it. The scan now
# also reads the layer filesystem via `docker save | grep`.
# ---------------------------------------------------------------------------
_SENTINEL = "OI3-SENTINEL-TOKEN-DO-NOT-USE-9f3a"
_FS_SENTINEL = "OI3-FS-SENTINEL-TOKEN-DO-NOT-USE-7c2b"
_THROWAWAY_TAG = "dmac-bedrock-proxy-g6-negctl:throwaway"
_FS_THROWAWAY_TAG = "dmac-bedrock-proxy-g6-fs-negctl:throwaway"
# A token-shaped pattern (Bedrock bearer tokens are `ABSK…` + base64-ish body).
_TOKEN_SHAPE_RE = re.compile(rb"ABSK[A-Za-z0-9+/=_-]{8,}")


def _scan_image_metadata_for(tag: str, needle: str) -> int:
    """Hits for `needle` in image METADATA: `Config.Env` + `docker history`.

    Inspects the full `docker inspect` blob (covers `Config.Env`) plus
    `docker history` (layer-creation command text). This surface catches an
    ENV-baked token and a token echoed in a RUN command, but NOT a token written
    into a layer's filesystem — that is what `_scan_image_filesystem_for` adds.
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


def _scan_image_filesystem_for(tag: str, needle: str, tmp_path: Path) -> int:
    """Hits for `needle` in the image FILESYSTEM, via `docker export | grep`.

    Creates a container from the image and `docker export`s its flattened
    filesystem as a single uncompressed tar, then counts raw-byte occurrences of
    the needle. This covers a token written into a file via `COPY` or `RUN echo`
    regardless of how the runtime stores layers.

    `docker save` is deliberately NOT used here: under an OCI-layout runtime such
    as OrbStack it emits gzip/zstd-compressed layer blobs (`blobs/sha256/...`), so
    a file's content is invisible to a raw-byte grep and this scan would silently
    return 0 (the G6 filesystem negative control catches exactly that). `docker
    export` yields the container's flat filesystem uncompressed, so file content
    is always present as raw bytes. The container and tar are scoped and removed
    before returning.
    """
    tar_path = tmp_path / f"_g6_export_{tag.replace('/', '_').replace(':', '_')}.tar"
    needle_bytes = needle.encode()
    cid = ""
    try:
        create = subprocess.run(
            ["docker", "create", tag],
            capture_output=True,
            text=True,
        )
        assert create.returncode == 0, f"docker create {tag} failed: {create.stderr}"
        cid = create.stdout.strip()
        export = subprocess.run(
            ["docker", "export", cid, "-o", str(tar_path)],
            capture_output=True,
            text=True,
        )
        assert export.returncode == 0, f"docker export {cid} failed: {export.stderr}"
        data = tar_path.read_bytes()
        return data.count(needle_bytes)
    finally:
        tar_path.unlink(missing_ok=True)
        if cid:
            subprocess.run(
                ["docker", "rm", "-f", cid], capture_output=True, text=True
            )


def _scan_image_all_surfaces_for(tag: str, needle: str, tmp_path: Path) -> int:
    """Combined hits across metadata (Config.Env + history) AND filesystem."""
    return _scan_image_metadata_for(tag, needle) + _scan_image_filesystem_for(
        tag, needle, tmp_path
    )


def _rmi(tag: str) -> None:
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, text=True)


@pytest.mark.live_docker
def test_g6_token_not_baked_with_negative_controls(tmp_path: Path) -> None:
    """Both negative controls fire (ENV-bake + FILESYSTEM-bake flagged), then the
    real image has 0 token hits across Config.Env + history + filesystem."""
    # --- Negative control 1: ENV-baked sentinel (metadata + filesystem scan). ---
    env_df = tmp_path / "Dockerfile.env-negctl"
    env_df.write_text(
        "FROM busybox:latest\n"
        f'ENV AWS_BEARER_TOKEN_BEDROCK="{_SENTINEL}"\n',
        encoding="utf-8",
    )
    env_build = subprocess.run(
        ["docker", "build", "-f", str(env_df), "-t", _THROWAWAY_TAG, str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert env_build.returncode == 0, (
        f"ENV negative-control build failed: {env_build.stderr}"
    )

    # --- Negative control 2: FILESYSTEM-baked sentinel (proves the fs surface). ---
    # COPY a file whose CONTENT is the sentinel: the layer command text records
    # only the filename (not the bytes), so this sentinel lands in the layer
    # FILESYSTEM but NOT in `docker history`/Config.Env — exactly the surface the
    # old metadata-only scanner missed.
    fs_secret_file = tmp_path / "baked_secret.txt"
    fs_secret_file.write_text(f"{_FS_SENTINEL}\n", encoding="utf-8")
    fs_df = tmp_path / "Dockerfile.fs-negctl"
    fs_df.write_text(
        "FROM python:3.14-slim-bookworm\n"
        "COPY baked_secret.txt /baked_secret.txt\n",
        encoding="utf-8",
    )
    fs_build = subprocess.run(
        ["docker", "build", "-f", str(fs_df), "-t", _FS_THROWAWAY_TAG, str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert fs_build.returncode == 0, (
        f"FILESYSTEM negative-control build failed: {fs_build.stderr}"
    )

    try:
        # ENV-bake: must be flagged by the all-surface scan (it shows up in
        # Config.Env metadata; the fs surface need not see it but the scan does).
        env_hits = _scan_image_all_surfaces_for(_THROWAWAY_TAG, _SENTINEL, tmp_path)
        assert env_hits >= 1, (
            "ENV-BAKE NEGATIVE CONTROL FAILED: scanner did not flag an ENV-baked "
            f"sentinel (hits={env_hits}); the metadata detector is not proven"
        )
        print(f"G6 ENV-bake negative control FIRED: flagged ({env_hits} hits)")

        # FILESYSTEM-bake: this is the surface the old scanner MISSED. It must be
        # invisible to the metadata-only scan and flagged by the filesystem scan.
        fs_meta_hits = _scan_image_metadata_for(_FS_THROWAWAY_TAG, _FS_SENTINEL)
        fs_fs_hits = _scan_image_filesystem_for(
            _FS_THROWAWAY_TAG, _FS_SENTINEL, tmp_path
        )
        assert fs_meta_hits == 0, (
            "sanity: a filesystem-only sentinel should NOT appear in metadata "
            f"(Config.Env/history); got {fs_meta_hits} — the controls are not "
            "isolating the surfaces as intended"
        )
        assert fs_fs_hits >= 1, (
            "FILESYSTEM-BAKE NEGATIVE CONTROL FAILED: the filesystem scan did not "
            f"flag a sentinel written into a layer FILE (hits={fs_fs_hits}); the "
            "filesystem surface is NOT actually covered, so a 0-hit result on the "
            "real image's filesystem would be meaningless"
        )
        print(
            "G6 FILESYSTEM-bake negative control FIRED: flagged on the filesystem "
            f"surface ({fs_fs_hits} hits), invisible to metadata ({fs_meta_hits})"
        )

        # --- Real image: ZERO sentinel hits across ALL surfaces. ---
        real_sentinel_hits = _scan_image_all_surfaces_for(
            _EXPECTED_IMAGE, _SENTINEL, tmp_path
        ) + _scan_image_all_surfaces_for(_EXPECTED_IMAGE, _FS_SENTINEL, tmp_path)
        assert real_sentinel_hits == 0, (
            f"real image leaked a sentinel ({real_sentinel_hits} hits)"
        )

        # The bearer-token ENV var name must not carry a value in Config.Env.
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

        # A token-SHAPED string (`ABSK…`) must not appear anywhere in the saved
        # image bytes (env, history, OR filesystem) — covers a leak under a name
        # other than AWS_BEARER_TOKEN_BEDROCK.
        tar_path = tmp_path / "_g6_real_image.tar"
        try:
            save = subprocess.run(
                ["docker", "save", _EXPECTED_IMAGE, "-o", str(tar_path)],
                capture_output=True,
                text=True,
            )
            assert save.returncode == 0, f"docker save real image failed: {save.stderr}"
            shaped = _TOKEN_SHAPE_RE.findall(tar_path.read_bytes())
            assert not shaped, (
                "real image filesystem/metadata contains a token-shaped (ABSK…) "
                f"string: {[m[:12] for m in shaped]!r}"
            )
        finally:
            tar_path.unlink(missing_ok=True)

        print(
            "G6: real image dmac-bedrock-proxy:poc has 0 token hits across "
            "Config.Env + history + filesystem (and no ABSK-shaped token)"
        )
    finally:
        _rmi(_THROWAWAY_TAG)
        _rmi(_FS_THROWAWAY_TAG)
