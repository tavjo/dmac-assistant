"""Live helpers for the T12 sidecar compose-E2E + containment suite.

This module is NOT a test module (leading underscore => not collected) and lives
under tests/integration/ (which is OUTSIDE the coverage-measured packages
`tests.harness` + `src/dmac_assistant`), so the live-only driving code here does
not count against the 95% hermetic coverage gate (recon:tests §1).

Everything here drives the REAL production surfaces:
  * agent containers via `dmac_assistant.containers.start_container` (the bridge's
    own spawn path, with the 16 shared-cred keys stripped by `_build_environment`);
  * the 9 NS ops via `docker exec` of the shipped plugin wrappers
    (/app/plugins/nextseek/bin/nextseek-*), i.e. the in-container runner -> sidecar
    WS / assistant viewset path;
  * raw WS frames to the sidecar from inside a container on the sidecar network
    (the only way to reach it — gate 15 means there is no host port binding).
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.config import BridgeConfig, UserRecord
from dmac_assistant.containers import start_container

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_IMAGE = "dmac-assistant:poc"

# Real compose container name (no container_name: in compose => derived
# <project>-<service>-<idx>). The plan's literal "nextseek-sidecar" is the
# *service* DNS name on the network, not the container name (known seam, decided
# in the T12 brief). Used only for `docker inspect` (gate 15) and stop/start.
SIDECAR_CONTAINER = "dmac-nextseek-sidecar-nextseek-sidecar-1"
# Service DNS name reachable from agent containers on the sidecar network.
SIDECAR_SERVICE_DNS = "nextseek-sidecar"
SIDECAR_NETWORK = "dmac-nextseek-net"

# macOS: agent containers attach ONLY to the sidecar network and cannot resolve
# the local NExtSEEK stack by Docker DNS, so the assistant viewset (query/plan)
# is reached via the host gateway. NEVER edit .env — per-invocation override.
AGENT_NEXTSEEK_URL = "http://host.docker.internal:8000"


# --------------------------------------------------------------------------- env

def _locate_env_file() -> Path:
    start = Path(__file__).resolve().parent
    for parent in [start, *start.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return start.parent / ".env"


def load_env_values() -> dict[str, str]:
    """Parse the canonical .env the same way tests/conftest.py does (quote-stripped)."""
    path = _locate_env_file()
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ns_credentials() -> tuple[str, str]:
    """(api_user, api_pass) from .env — the local stack's `demo` login."""
    env = load_env_values()
    return env.get("NEXTSEEK_USERNAME", ""), env.get("NEXTSEEK_PASSWORD", "")


# ------------------------------------------------------------------- compose mgmt

def _make(target: str, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", target],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sidecar_up() -> None:
    _make("sidecar-up")


def sidecar_down() -> None:
    _make("sidecar-down")


def sidecar_inspect_port_bindings() -> Any:
    """`docker inspect <real-name> --format '{{json .HostConfig.PortBindings}}'`."""
    out = subprocess.run(
        ["docker", "inspect", SIDECAR_CONTAINER,
         "--format", "{{json .HostConfig.PortBindings}}"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"docker inspect failed: {out.stderr.strip()}")
    return json.loads(out.stdout.strip())


def sidecar_stop() -> None:
    subprocess.run(["docker", "stop", SIDECAR_CONTAINER], capture_output=True, timeout=60)


def sidecar_start() -> None:
    subprocess.run(["docker", "start", SIDECAR_CONTAINER], capture_output=True, timeout=60)


# ---------------------------------------------------------------- bridge plumbing

def make_bridge_config(tmp_path: Path, *, staging_root: Path) -> BridgeConfig:
    """A real BridgeConfig wired to the sidecar network + a tmp staging root.

    staging_root is pinned to a tmp dir (NEVER the default
    ~/dmac-dev/nextseek-sidecar-staging) so the sweep can never delete the real
    sidecar staging tree (task-04R1 lesson)."""
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    for sub in ("claude-users", "scratch", "dropbox", "output"):
        (tmp_path / sub).mkdir(exist_ok=True)
    return BridgeConfig(
        users={"demo": UserRecord(password="unused-for-exec", projects=["proj-a"])},
        claude_users_root=tmp_path / "claude-users",
        scratch_root=tmp_path / "scratch",
        dropbox_root=tmp_path / "dropbox",
        output_root=tmp_path / "output",
        catalog_file=catalog,
        sidecar_network=SIDECAR_NETWORK,
        sidecar_staging_root=staging_root,
        bridge_host="127.0.0.1",
        bridge_port=8000,
    )


def make_identity(user_id: str, password: str,
                  projects: list[str] | None = None) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id=user_id, password=password, projects=projects or ["proj-a"]
    )


def start_decred_agent(
    identity: AuthenticatedIdentity,
    config: BridgeConfig,
    bridge_env: dict[str, str],
):
    """Spawn an IDLE de-credentialed agent via the production start_container path.

    command_override=sleep infinity mirrors the real idle-container boot (the bridge
    execs every turn into an idle container); without it start_container would launch
    the `claude` CLI and block on stdin. The 16 shared-cred keys are stripped by
    _build_environment regardless of what bridge_env carries."""
    # Pre-create the per-user mount dirs so docker does not create them root-owned.
    for root in (config.scratch_root, config.output_root):
        (root / identity.user_id).mkdir(parents=True, exist_ok=True)
    (config.claude_users_root / identity.user_id / ".claude").mkdir(parents=True, exist_ok=True)
    return start_container(
        identity,
        image=AGENT_IMAGE,
        session_id=None,
        bridge_env=bridge_env,
        config=config,
        command_override=["sleep", "infinity"],
    )


@dataclass
class OpResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def terminal_json(self) -> dict:
        """Parse the last stdout line as JSON (the runner emits one result line)."""
        line = self.stdout.strip().splitlines()[-1] if self.stdout.strip() else "{}"
        return json.loads(line)


def exec_in_agent(container, argv: list[str], *, env: dict[str, str] | None = None,
                  timeout: int = 240) -> OpResult:
    """docker exec into the idle agent, demuxed stdout/stderr + exit code."""
    api = container.client.api
    exec_id = api.exec_create(
        container.id, cmd=argv, stdin=False, stdout=True, stderr=True,
        tty=False, environment=env or {},
    )["Id"]
    # exec_start streaming so a hung op cannot block forever (the runner has its
    # own 300s WS recv timeout; this outer wall-clock guards the test).
    stream = api.exec_start(exec_id, stream=True, demux=True)
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    for stdout_b, stderr_b in stream:
        if stdout_b:
            out_chunks.append(stdout_b)
        if stderr_b:
            err_chunks.append(stderr_b)
        if time.monotonic() > deadline:
            raise TimeoutError(f"exec {argv!r} exceeded {timeout}s")
    info = api.exec_inspect(exec_id)
    return OpResult(
        name=argv[-1] if argv else "?",
        exit_code=int(info.get("ExitCode") or 0),
        stdout=b"".join(out_chunks).decode("utf-8", "replace"),
        stderr=b"".join(err_chunks).decode("utf-8", "replace"),
    )


# ------------------------------------------------------ the 9 ops in one container

_BIN = "/app/plugins/nextseek/bin"

# Read-class queries chosen to FUNCTION against a data-light stack: each op must
# complete and return a typed result (exit 0). Empty result sets are fine —
# "function" means the agent->sidecar/viewset transport + dispatch succeeded.
_NDMA = "find mouse samples treated with NDMA"


@dataclass
class NineOpRun:
    results: list[OpResult] = field(default_factory=list)
    frames: list[str] = field(default_factory=list)
    settings: str = ""

    @property
    def all_succeeded(self) -> bool:
        return all(r.ok for r in self.results)

    def summary(self) -> str:
        return ", ".join(f"{r.name}={r.exit_code}" for r in self.results)


def warm_sidecar(container) -> None:
    """Pay the cold-start tax (ChatConfig init + first LLM call can exceed the
    websockets default 20s keepalive on a freshly-booted sidecar) with one cheap
    op BEFORE the timed/asserted ops, so later ops complete inside the window.
    The result is intentionally ignored."""
    exec_in_agent(container, [f"{_BIN}/nextseek-entity-extract", "--query", _NDMA], timeout=120)


def settings_surface(bridge_env: dict[str, str]) -> str:
    """The REAL production `--settings '{...}'` cmdline string for this bridge_env.

    The auto-mode classifier settings JSON rides the CC exec cmdline (built by
    `_automode_settings_args`), NOT the container env — so the gate-1 canary scan must
    cover it too, or a re-keying of a shared canary into an autoMode `environment`
    entry would slip the scan. This calls the exact production builder and joins its
    parts, yielding the literal string the bridge would pass to `claude`."""
    from dmac_assistant.containers import _automode_settings_args
    return " ".join(_automode_settings_args(bridge_env))


def run_nine_ops(container) -> NineOpRun:
    """Drive all 9 ops through ONE de-cred container; collect frames for the canary
    scan. Binds gate 1's conjunction: a non-functional container fails .all_succeeded."""
    run = NineOpRun()

    def drive(name: str, argv: list[str], env: dict[str, str] | None = None,
              timeout: int = 240) -> OpResult:
        res = exec_in_agent(container, argv, env=env, timeout=timeout)
        res.name = name
        run.results.append(res)
        run.frames.append(res.stdout)
        run.frames.append(res.stderr)
        return res

    # 7 granular ops (agent bin -> sidecar WS -> portable.py)
    drive("entity", [f"{_BIN}/nextseek-entity-extract", "--query", _NDMA])
    parse = drive("parse", [f"{_BIN}/nextseek-parse", "--query", _NDMA])
    drive("graph", [f"{_BIN}/nextseek-graph", "--query",
                    "show lineage of mouse samples"])

    # api-read + api-write both feed a real parser plan (the parse op output) so the
    # API agent builds a real request. The chosen plan targets a read-safe SEARCH
    # endpoint (advanced_search) — non-mutating — so the confirmed-write op exercises
    # the FULL write path (client L2 + server gate + dispatch + execution) WITHOUT
    # corrupting the shared stack. Falls back to a minimal plan if parse failed.
    try:
        parser_plan = parse.terminal_json()
    except Exception:
        parser_plan = {}
    if not parser_plan.get("target_endpoint"):
        parser_plan = {"mode": "new_search",
                       "target_endpoint": "/nextseek_api/samples/advanced_search/",
                       "filters": {}}
    plan_json = json.dumps(parser_plan)
    drive("api-read", [f"{_BIN}/nextseek-api-read", "--parser-plan", plan_json])
    drive("api-write", [f"{_BIN}/nextseek-api-write", "--parser-plan", plan_json,
                        "--confirmed-write"])

    drive("report", [f"{_BIN}/nextseek-report", "--mode", "published",
                     "--project", "Published Data"])
    drive("generate-submission",
          [f"{_BIN}/nextseek-generate-submission", "--type", "GEO", "--uids", "1"])

    # query + plan (agent bin -> assistant viewset query/async + progress polling)
    drive("query", [f"{_BIN}/nextseek-query", "--query",
                    "how many samples are in the database"], timeout=300)
    drive("plan", [f"{_BIN}/nextseek-plan", "--query",
                   "how many samples are in the database"], timeout=300)
    return run


# ----------------------------------------------------- raw WS frame from in-network

def raw_ws_frame_via_agent(container, frame: dict, *, host: str = SIDECAR_SERVICE_DNS,
                           port: int = 8765, timeout: int = 120) -> dict:
    """Send an arbitrary JSON frame to the sidecar from INSIDE the agent container
    (the only vantage point that can reach the port-less sidecar — gate 15), bypassing
    the advisory client checks. Returns the parsed sidecar response."""
    script = (
        "import json,sys\n"
        "from websockets.sync.client import connect\n"
        f"ws=connect('ws://{host}:{port}', open_timeout=10, ping_interval=None)\n"
        f"ws.send(json.dumps({json.dumps(frame)}))\n"
        "sys.stdout.write(ws.recv(timeout=120))\n"
        "ws.close()\n"
    )
    res = exec_in_agent(container, ["python", "-c", script], timeout=timeout)
    return json.loads(res.stdout.strip().splitlines()[-1])
