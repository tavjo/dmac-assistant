"""T10 — live PAID batch-upload E2E driver (dmac bridge / WebSocket path).

Drives ONE real Claude Code agent turn against the LOCAL dmac-assistant stack: launches the dmac
bridge, logs in, sends a batch-upload request over ``/ws/chat`` (the path a lab user hits), and the
bridge spawns a real ``dmac-assistant:poc`` agent container whose turn reads the batch-upload
SKILL.md and runs the ``nextseek-*`` shims to build + validate a workbook. The turn's authoritative
cost is captured from the ``session_ended.total_cost_usd`` frame into a pre-call-capped SpendLedger.

The batch-upload flow spends no money itself — the CC agent turn is the paid inference. The system
under test is the LOCAL dmac stack; the NExtSEEK step7d harness is a rigor reference only.

ALL verdict/cost/bundle logic lives in the covered ``batch_upload_live_evidence`` module; this driver
is the thin live-orchestration shell. The live functions carry ``# pragma: no cover`` (paid-only path,
plan Coverage-Exceptions closed set: launch/turn/login/wait/teardown/async_main).

Usage:
    # $0 preflight (no spend) — checks creds, image, sidecar, bridge boot:
    uv run python tools/e2e/run_batch_upload_live_e2e.py --preflight-only
    # PAID run (explicit per-session owner paid-API authorization + $5 cap):
    uv run python tools/e2e/run_batch_upload_live_e2e.py --paid --cap 5.00 --query "<request>"

Env: NEXTSEEK_USERNAME/NEXTSEEK_PASSWORD (bridge login + forwarded to the container), DMAC_E2E_NS_URL
(the agent-reachable NExtSEEK base for the validate call against the local stack), optional
DMAC_T10_QUERY, DMAC_E2E_PROJECT.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import UTC, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dotenv import load_dotenv  # noqa: E402
from websockets.asyncio.client import connect as ws_connect  # noqa: E402

from tools.e2e.batch_upload_live_evidence import (  # noqa: E402
    extract_cost,
    write_evidence_bundle,
)
from tools.e2e.ledger import LedgerCeilingError, SpendLedger  # noqa: E402
from tools.e2e.verify_batch_upload_live import POLICY_CAP_USD, clamp_cap  # noqa: E402
from tools.e2e.run_router_e2e import (  # noqa: E402
    BRIDGE_READY_TIMEOUT_S,
    _build_child_env,
    _check_credentials,
    _check_image,
    _free_port,
    _launch_bridge,
    _login,
    _synthetic_project,
    _terminate_bridge,
    _wait_for_ready,
)

EVIDENCE_ROOT = REPO_ROOT / "evidence" / "batch-upload-e2e"
DEFAULT_CAP_USD = 5.00
# Conservative pre-call reservation for one Opus turn; settled with the real figure after.
PROJECTED_TURN_USD = 0.50
BEDROCK_MODEL = "claude-opus-4-8 (Bedrock, via proxy)"
PER_TURN_TIMEOUT_S = 600.0

DEFAULT_QUERY = (
    "Use the NExtSEEK batch-upload skill to prepare and validate an upload workbook for a small "
    "sample update. Resolve the project by name and get it confirmed, fetch the SampleType schema, "
    "build the rows, and validate the workbook in file mode. Do NOT submit or start any upload — "
    "return the generated workbook path and the validation result."
)

REPRODUCE_CMD = (
    "uv run python tools/e2e/run_batch_upload_live_e2e.py --paid --cap 5.00\n"
    "# then verify the bundle ($0, recomputes from the transcript):\n"
    "uv run python tools/e2e/verify_batch_upload_live.py "
    "evidence/batch-upload-e2e/<ts>/live_e2e_transcript.json"
)


_PROXY_NETWORK = os.environ.get("DMAC_SIDECAR_NETWORK", "dmac-nextseek-net")
_PROXY_ALIAS = "bedrock-proxy"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def apply_cap_to_child_env(child_env: dict, cap_usd: float) -> dict:
    """PREVENTION, not just detection: make Claude Code itself halt the turn at the policy cap
    via its own ``--max-budget-usd`` (else the container default $10 bounds the spend, 2x the $5
    cap). The forwarded value is clamp_cap-bounded so NO caller can loosen the policy ceiling.
    Module-level and NOT under ``# pragma: no cover`` — this line is load-bearing and must stay
    unit-testable (fix LOW-2 / re-vet round 3)."""
    child_env["DMAC_CC_MAX_BUDGET_USD"] = f"{clamp_cap(cap_usd):.2f}"
    return child_env


def _check_bedrock_proxy(network: str = _PROXY_NETWORK, alias: str = _PROXY_ALIAS) -> str | None:
    """Return an error string if the T10 dependency is unmet, else None.

    T10 is a ``container_cc`` paid turn: the agent reaches Bedrock via the de-credentialing proxy at
    ``http://bedrock-proxy:8080`` on the sidecar network (config default ``dmac-nextseek-net``). The
    NS shared-cred sidecar is NOT used by the batch-upload skill, so — unlike the router E2E — we do
    NOT require it; we require the network to exist AND a RUNNING container carrying the
    ``bedrock-proxy`` network alias on it.
    """
    try:
        net = subprocess.run(
            ["docker", "network", "inspect", network, "--format", "{{json .Containers}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"could not verify bedrock proxy: {type(exc).__name__}"
    if net.returncode != 0:
        return f"network {network!r} not found; build+run the dmac Bedrock proxy on it first"
    try:
        containers = json.loads(net.stdout or "{}") or {}
    except json.JSONDecodeError:
        containers = {}
    for cid in containers:
        insp = subprocess.run(
            ["docker", "inspect", cid, "--format",
             '{{.State.Status}} {{json (index .NetworkSettings.Networks "' + network + '").Aliases}}'],
            capture_output=True, text=True, timeout=10, check=False,
        )
        out = insp.stdout.strip()
        if out.startswith("running") and f'"{alias}"' in out:
            return None
    return f"no running {alias!r} container on network {network!r}; build+run the dmac Bedrock proxy"


def preflight() -> list[str]:
    """$0 readiness checks. Returns a list of problems (empty == ready)."""
    problems: list[str] = []
    missing = _check_credentials()
    if missing:
        problems.append(f"missing credentials: {', '.join(missing)}")
    if not _check_image():
        problems.append("dmac-assistant:poc image not found (make image-build)")
    proxy = _check_bedrock_proxy()
    if proxy is not None:
        problems.append(f"bedrock proxy precondition failed: {proxy}")
    return problems


async def _run_live_turn(*, port: int, token: str, query: str) -> tuple[list[dict], str | None]:  # pragma: no cover - paid live path
    """Drive one paid CC turn over /ws/chat; return (frames, transport_error)."""
    frames: list[dict] = []
    transport_error: str | None = None
    uri = f"ws://127.0.0.1:{port}/ws/chat"
    try:
        async with asyncio.timeout(PER_TURN_TIMEOUT_S):
            async with ws_connect(
                uri, additional_headers={"authorization": f"Bearer {token}"}
            ) as ws:
                await ws.send(json.dumps({"type": "user_message", "content": query}))
                while True:
                    frame = json.loads(await ws.recv())
                    frames.append(frame)
                    if frame.get("type") == "session_ended":
                        break
    except TimeoutError:
        transport_error = "timeout"
    except Exception as exc:  # noqa: BLE001 - E2E must record, not raise
        transport_error = f"{type(exc).__name__}: {exc}"
    return frames, transport_error


async def _async_main(*, cap_usd: float, query: str, evidence_root: pathlib.Path) -> int:  # pragma: no cover - paid live path
    problems = preflight()
    if problems:
        for p in problems:
            print(f"[T10] preflight FAILED: {p}", file=sys.stderr)
        return 2

    out_dir = evidence_root / _utc_now()
    ledger = SpendLedger(session_cap_usd=cap_usd)

    # Pre-call abort: never START the turn if the projected cost would breach the cap.
    try:
        ledger.reserve("cc_turn", model=BEDROCK_MODEL, projected_usd=PROJECTED_TURN_USD)
    except LedgerCeilingError as exc:
        print(f"[T10] {exc}", file=sys.stderr)
        write_evidence_bundle(
            out_dir, query=query, frames=[], cap_usd=cap_usd, ledger_total_usd=0.0,
            transport_error="ledger_ceiling_refused", aborted_on_budget=True,
            reproduce_cmd=REPRODUCE_CMD, extra_meta={"reserved_only": True},
        )
        ledger.save(out_dir / "ledger.jsonl")
        return 1

    port = _free_port()
    scratch_root = out_dir / "scratch_state"
    dropbox_root = out_dir / "dropbox_state"
    # The bridge + Popen log files need these to exist BEFORE launch (mirrors
    # run_router_e2e._async_main's mkdirs; without them _launch_bridge crashes pre-spawn).
    for d in (out_dir, scratch_root, out_dir / "output_state", dropbox_root,
              out_dir / "ns-stderr", dropbox_root / _synthetic_project()):
        d.mkdir(parents=True, exist_ok=True)
    child_env = _build_child_env(
        scratch_root=scratch_root,
        output_root=out_dir / "output_state",
        dropbox_root=dropbox_root,
        catalog_file=REPO_ROOT / "vendor" / "chat_nextseek" / "agent_model_catalog.json",
        ns_stderr_dir=out_dir / "ns-stderr",
    )
    # PREVENTION, not just detection — the covered module-level helper forwards the clamped cap.
    apply_cap_to_child_env(child_env, cap_usd)
    proc = _launch_bridge(
        port=port, child_env=child_env,
        stdout_log=out_dir / "bridge.stdout.log", stderr_log=out_dir / "bridge.stderr.log",
    )
    frames: list[dict] = []
    transport_error: str | None = None
    try:
        if not _wait_for_ready(port=port, deadline=time.monotonic() + BRIDGE_READY_TIMEOUT_S):
            transport_error = "bridge_not_ready"
        else:
            token = _login(port=port)
            frames, transport_error = await _run_live_turn(port=port, token=token, query=query)
    finally:
        _terminate_bridge(proc)

    # Settle the ledger with the AUTHORITATIVE figure from the turn's own result frame.
    cost = extract_cost(frames)
    ledger.record(
        "cc_turn", model=BEDROCK_MODEL,
        in_tokens=int(cost.usage.get("input_tokens", 0) or 0),
        out_tokens=int(cost.usage.get("output_tokens", 0) or 0),
        actual_usd=float(cost.cost_usd),
    )
    ledger.save(out_dir / "ledger.jsonl")

    summary = write_evidence_bundle(
        out_dir, query=query, frames=frames, cap_usd=cap_usd,
        ledger_total_usd=ledger.running_usd, transport_error=transport_error,
        aborted_on_budget=False, reproduce_cmd=REPRODUCE_CMD,
        extra_meta={"cost_source": cost.cost_source, "bridge_port": port},
    )
    print(json.dumps({
        "bundle": str(out_dir),
        "all_pass": summary["all_pass"],
        "total_cost_usd": summary["total_cost_usd"],
        "cost_source": cost.cost_source,
        "within_cap": summary["within_cap"],
    }, sort_keys=True))
    return 0 if summary["all_pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T10 live paid batch-upload E2E (bridge/WS path)")
    parser.add_argument("--paid", action="store_true",
                        help="REQUIRED to spend. Without it, only $0 preflight runs.")
    parser.add_argument("--cap", type=float, default=DEFAULT_CAP_USD,
                        help=f"Hard spend cap in USD (default {DEFAULT_CAP_USD}; "
                             f"clamped to the policy ceiling ${POLICY_CAP_USD:.2f}, may only tighten).")
    parser.add_argument("--query", default=None, help="Override the batch-upload request.")
    parser.add_argument("--evidence-root", type=pathlib.Path, default=EVIDENCE_ROOT)
    parser.add_argument("--preflight-only", action="store_true",
                        help="Run $0 readiness checks and exit (no bridge, no spend).")
    args = parser.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env.dev", override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)

    query = args.query or os.environ.get("DMAC_T10_QUERY") or DEFAULT_QUERY
    cap = clamp_cap(args.cap)  # never loosen the policy ceiling

    if args.preflight_only or not args.paid:
        problems = preflight()
        status = "READY" if not problems else "NOT READY"
        print(json.dumps({"preflight": status, "problems": problems,
                          "paid": bool(args.paid), "note":
                          "pass --paid (with per-session owner authorization) to run the paid turn"},
                         sort_keys=True))
        return 0 if not problems else 2

    return asyncio.run(_async_main(cap_usd=cap, query=query,
                                   evidence_root=args.evidence_root))


if __name__ == "__main__":
    raise SystemExit(main())
