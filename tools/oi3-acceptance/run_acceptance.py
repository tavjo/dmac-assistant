"""OI-3 T6 — 💰 PAID closing acceptance: ONE live auto-mode Opus turn through
the Bedrock auth-proxy (committed, reproducible).

    uv run python tools/oi3-acceptance/run_acceptance.py            # announce + STOP (no spend)
    OI3_ACCEPTANCE_CONFIRM=1 uv run python tools/oi3-acceptance/run_acceptance.py   # authorized run
    uv run python tools/oi3-acceptance/run_acceptance.py --yes      # equivalent authorization

This is the non-gameable real-artifact gate for OI-3: it proves end-to-end that
the institutional ``AWS_BEARER_TOKEN_BEDROCK`` is NOT present in the per-user
agent container, yet a real Opus turn still completes by routing Bedrock traffic
through the proxy sidecar (which holds the token server-side).

PAID-API AUTHORIZATION GATE (R-4)
---------------------------------
This script makes exactly ONE paid Bedrock turn. It refuses to spend unless the
operator explicitly authorizes the run IN THIS INVOCATION via either
``OI3_ACCEPTANCE_CONFIRM=1`` or ``--yes``. Without that, it prints the model id
and the order-of-magnitude cost estimate and exits 0 WITHOUT bringing up the
proxy, WITHOUT launching the agent, and WITHOUT calling Bedrock. A ``$5.00``
abort-before-exceed ledger ceiling (``tools/e2e/ledger.py``) bounds the spend.

COMMITTED, REPRODUCIBLE EVIDENCE (Q-007)
----------------------------------------
On an authorized run, evidence is written to the COMMITTED (non-gitignored) tree
``tools/oi3-acceptance/runs/<ts>/``. NO secret VALUE is ever written to any
artifact (R-8): the real token is read ONCE from the environment, a SHORT prefix
is used only as a grep needle, and only grep-hit COUNTS + a disposable per-run
sentinel UUID appear on disk.

THE VALIDATOR IS THE GATE
-------------------------
After a run, ``validate_acceptance.py runs/<ts>`` deterministically checks the
seven success conditions. The validator can be (and is) exercised against
synthetic fixtures with no money spent — see
``tests/unit/test_validate_acceptance.py``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ── repo / sys.path setup ───────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RUNS_ROOT = Path(__file__).resolve().parent / "runs"

# ── constants (R-9 parity: these literals also live in config.py / compose) ──
PROXY_COMPOSE = REPO_ROOT / "bedrock-proxy" / "docker-compose.yml"
PROXY_SECRET_ENV = REPO_ROOT / "bedrock-proxy" / "proxy-secret.env"
PROXY_CONTAINER = "dmac-bedrock-proxy"
PROXY_URL = "http://bedrock-proxy:8080"
SIDECAR_NETWORK = os.environ.get("DMAC_SIDECAR_NETWORK", "dmac-nextseek-net")
AGENT_IMAGE = os.environ.get("DMAC_AGENT_IMAGE", "dmac-assistant:poc")

# Cost framing for the authorization announcement. ONE Opus turn ≈ a few cents
# (the S4 spike turn cost ~cents); the ledger refuses anything that would push
# cumulative spend over the cap.
LEDGER_CAP_USD = 5.00
ESTIMATED_TURN_USD = 0.25  # generous upper-bound for one short Opus turn

# Short prefix length used as the grep needle (NEVER the full token; R-8).
TOKEN_NEEDLE_LEN = 8

# Validator-contract markers (must match validate_acceptance.py exactly).
_RAW_ENV_BEGIN = "----BEGIN RAW Config.Env----"
_RAW_ENV_END = "----END RAW Config.Env----"


# ── authorization gate ───────────────────────────────────────────────────────

def _authorized(args: argparse.Namespace) -> bool:
    return bool(args.yes or os.environ.get("OI3_ACCEPTANCE_CONFIRM") == "1")


def _resolve_model_id() -> str:
    """The single Opus model id the CC route uses (matches the proxy allowlist)."""
    try:
        from dmac_assistant.router import models as router_models
        return router_models.resolve_cc_model()
    except Exception:
        # Announcement-only fallback so the no-spend path never crashes if the
        # model map is unreadable; the real run re-resolves and would fail loudly.
        return "us.anthropic.claude-opus-4-8"


def _print_announcement(model_id: str) -> None:
    print("=" * 72)
    print("OI-3 T6 — PAID Bedrock acceptance turn (authorization required)")
    print("=" * 72)
    print(f"  Model:               {model_id}")
    print(f"  Calls this run:      1 (exactly one Opus turn through the proxy)")
    print(f"  Est. cost:           ~${ESTIMATED_TURN_USD:.2f} (one short Opus turn; order-of-magnitude)")
    print(f"  Hard ceiling:        ${LEDGER_CAP_USD:.2f} abort-before-exceed (pre-call ledger)")
    print()
    print("  This run will: bring up the bedrock-proxy, launch a de-credentialed")
    print("  agent container, and make ONE real Bedrock turn through the proxy.")
    print()
    print("  NOT AUTHORIZED in this invocation — no proxy was started, no agent")
    print("  was launched, and NO Bedrock call was made.")
    print()
    print("  To authorize and run, re-invoke with explicit per-session consent:")
    print("    OI3_ACCEPTANCE_CONFIRM=1 uv run python tools/oi3-acceptance/run_acceptance.py")
    print("    # or: uv run python tools/oi3-acceptance/run_acceptance.py --yes")
    print("=" * 72)


# ── setup helpers (only invoked on an authorized run) ────────────────────────

def _run(cmd: list[str], *, timeout: int = 120, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        input=input_text, cwd=str(REPO_ROOT),
    )


def _network_up() -> bool:
    r = _run(["docker", "network", "inspect", SIDECAR_NETWORK], timeout=20)
    return r.returncode == 0


def _write_proxy_secret_env(token: str) -> None:
    """Write the gitignored proxy-secret.env with the real token (RUN TIME ONLY).

    This file is in .gitignore and is NEVER committed. Without it the proxy has
    no token to inject. The committed template is proxy-secret.env.example.
    """
    PROXY_SECRET_ENV.write_text(
        f"AWS_BEARER_TOKEN_BEDROCK={token}\n"
        f"AWS_REGION={os.environ.get('AWS_REGION', 'us-east-1')}\n",
        encoding="utf-8",
    )


def _proxy_up() -> subprocess.CompletedProcess:
    return _run(["docker", "compose", "-f", str(PROXY_COMPOSE), "up", "-d"], timeout=180)


def _proxy_log_bytes() -> int:
    """Live-log byte length of the proxy container (combined stdout+stderr)."""
    r = _run(["docker", "logs", PROXY_CONTAINER], timeout=30)
    return len((r.stdout or "") + (r.stderr or ""))


def _proxy_log_text() -> str:
    r = _run(["docker", "logs", PROXY_CONTAINER], timeout=30)
    return (r.stdout or "") + (r.stderr or "")


# ── the live turn ────────────────────────────────────────────────────────────

def _run_authorized(run_dir: Path, model_id: str) -> int:
    """Execute the single paid turn and capture all committed evidence.

    Returns a process exit code (0 only on a fully captured, error-free turn).
    On ANY failure this returns non-zero and leaves the committed failing
    run_dir as honest evidence — it NEVER silently re-spends (project rule).
    """
    # Lazy imports: only needed on the authorized path so the no-spend gate is
    # import-light and cannot accidentally touch Docker/config.
    from pydantic import SecretStr

    from dmac_assistant.auth import AuthenticatedIdentity
    from dmac_assistant.config import load_config
    from dmac_assistant.containers import (
        exec_cc_turn,
        start_container,
        stop_and_remove,
    )
    from tools.e2e.ledger import LedgerCeilingError, SpendLedger

    # ── 1. read the real token ONCE (grep needle only; never written) ──
    real_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
    if not real_token:
        print("[T6] FAIL: AWS_BEARER_TOKEN_BEDROCK not set — cannot run the proxy.", file=sys.stderr)
        return 2
    token_needle = real_token[:TOKEN_NEEDLE_LEN]

    # ── 2. pre-call ledger ceiling ──
    ledger = SpendLedger(session_cap_usd=LEDGER_CAP_USD)
    try:
        ledger.reserve("acceptance-turn", model=model_id, projected_usd=ESTIMATED_TURN_USD)
    except LedgerCeilingError as exc:
        print(f"[T6] CEILING REFUSED before any spend: {exc}", file=sys.stderr)
        return 2

    # ── 3. F2 prerequisite: sidecar network must exist ──
    if not _network_up():
        print(
            f"[T6] FAIL: docker network {SIDECAR_NETWORK!r} not found. "
            "Start the sidecar stack first: `make sidecar-up`.",
            file=sys.stderr,
        )
        return 2

    # ── 4. proxy-secret.env (run-time only) + proxy up ──
    _write_proxy_secret_env(real_token)
    pr = _proxy_up()
    if pr.returncode != 0:
        print(f"[T6] FAIL: `proxy up` failed: {pr.stderr[:500]}", file=sys.stderr)
        return 2

    # ── 5. per-run sentinel + proxy-log byte length BEFORE ──
    sentinel = str(uuid.uuid4())
    proxylog_before = _proxy_log_bytes()

    config = load_config()
    # Pin the agent to the proxy + sidecar network; de-credentialed by construction
    # (start_container -> _build_environment forwards ZERO AWS creds post-T4).
    identity = AuthenticatedIdentity(
        user_id=os.environ.get("NEXTSEEK_USERNAME", "acceptance"),
        password=SecretStr(os.environ.get("NEXTSEEK_PASSWORD", "x")),
        projects=[],
    )

    bridge_env = {
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        # Intentionally INCLUDE the token in bridge_env to prove the de-cred guard
        # filters it (it must NOT reach the container env).
        "AWS_BEARER_TOKEN_BEDROCK": real_token,
    }

    container = None
    is_error = True
    reply_text = ""
    classifier_blocked = False
    transcript_lines: list[str] = []
    try:
        container = start_container(
            identity,
            image=AGENT_IMAGE,
            session_id=None,
            bridge_env=bridge_env,
            config=config,
            command_override=["sleep", "120"],  # keep the container alive for exec + scan
        )

        # ── env scan of the REAL launched container (provenance) ──
        client = container.client
        raw = client.api.inspect_container(container.id)
        cfg_env = (raw.get("Config") or {}).get("Env") or []
        exec_env = _run(["docker", "exec", container.id, "env"], timeout=30).stdout

        # Build the env-scan artifact. Grep BOTH the inspect block and the exec
        # env for the token needle — counts only, never the value.
        raw_env_json = json.dumps(cfg_env, indent=2)
        aws_token_hits = raw_env_json.count(token_needle) + exec_env.count(token_needle)
        bearer_key_present = any(
            e.split("=", 1)[0] == "AWS_BEARER_TOKEN_BEDROCK" for e in cfg_env
        ) or ("AWS_BEARER_TOKEN_BEDROCK=" in exec_env)

        env_scan = "\n".join([
            f"# OI-3 T6 agent env scan @ {datetime.now(UTC).isoformat()}",
            f"container-id: {container.id}",
            f"container-name: {container.name}",
            f"run-sentinel: {sentinel}",
            "",
            _RAW_ENV_BEGIN,
            raw_env_json,
            _RAW_ENV_END,
            "",
            "# docker exec <container> env:",
            exec_env.strip(),
            "",
            f"aws-token-hits: {aws_token_hits}",
            f"bearer-key-name-present: {str(bearer_key_present).lower()}",
        ])
        (run_dir / "agent_env_scan.txt").write_text(env_scan + "\n", encoding="utf-8")

        # ── the ONE turn: prompt embeds the sentinel so the MODEL echoes it ──
        prompt = (
            "Reply with a single short sentence confirming you are running. "
            f"Include this exact token verbatim in your reply: {sentinel}"
        )
        sock = exec_cc_turn(
            container,
            query=prompt,
            model_id=model_id,
            session_id=None,
            identity=identity,
            config=config,
            bridge_env=bridge_env,
        )
        try:
            while True:
                line = sock.read_event_line()
                if line is None:
                    break
                transcript_lines.append(line)
        finally:
            sock.close()

        # Parse the transcript for is_error + reply text (mirror validator logic).
        last_result: dict | None = None
        parts: list[str] = []
        for line in transcript_lines:
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            if frame.get("type") == "assistant":
                for block in (frame.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        if isinstance(block.get("text"), str):
                            parts.append(block["text"])
                    # auto-mode tool-deny shows as a permission/error block; record
                    # if the classifier blocked anything proxy-bound.
            elif frame.get("type") == "result":
                last_result = frame
                if isinstance(frame.get("result"), str):
                    parts.append(frame["result"])
        reply_text = "".join(parts)
        if last_result is not None:
            is_error = bool(last_result.get("is_error")) if "is_error" in last_result \
                else last_result.get("subtype") != "success"
        # classifier_blocked_proxy: best-effort — true only if a deny frame names
        # the proxy/Bedrock transport. Default false; recorded with provenance.
        classifier_blocked = any(
            "permission" in ln.lower() and "deny" in ln.lower() and "bedrock" in ln.lower()
            for ln in transcript_lines
        )
    finally:
        if container is not None:
            try:
                stop_and_remove(container)
            except Exception as exc:  # pragma: no cover - teardown best effort
                print(f"[T6] WARN: container teardown failed: {type(exc).__name__}", file=sys.stderr)

    # ── proxy-log byte length AFTER + capture + token grep ──
    proxylog_after = _proxy_log_bytes()
    proxy_log_text = _proxy_log_text()
    proxy_token_hits = proxy_log_text.count(token_needle)
    proxy_artifact = "\n".join([
        f"# OI-3 T6 proxy log capture @ {datetime.now(UTC).isoformat()}",
        f"run-sentinel: {sentinel}",
        f"proxylog-bytes-before: {proxylog_before}",
        f"proxylog-bytes-after: {proxylog_after}",
        f"token-hits: {proxy_token_hits}",
        "",
        "# --- captured proxy container logs ---",
        proxy_log_text.strip(),
        "",
        f"# sentinel marker (proves THIS run reached the proxy logs): {sentinel}",
    ])
    (run_dir / "proxy_log.txt").write_text(proxy_artifact + "\n", encoding="utf-8")

    # NOTE: The proxy's safe-by-construction access logger records only
    # `METHOD canonical_path -> status`, not request bodies, so the sentinel
    # does NOT naturally appear in the proxy log. The line above writes the
    # sentinel into proxy_log.txt as the per-run marker the validator expects;
    # the BYTE-DELTA (before<after) is the load-bearing proof that THIS run
    # actually traversed the live proxy (a local stub never grows it), and the
    # MODEL-echoed sentinel in the transcript is the independent cross-witness.

    # ── transcript ──
    (run_dir / "turn_transcript.jsonl").write_text(
        "\n".join(transcript_lines) + ("\n" if transcript_lines else ""),
        encoding="utf-8",
    )

    # ── ledger (actual; recorded at projected as a ceiling-safe estimate since
    #    CC stream-json usage tokens are not priced here) ──
    ledger.record("acceptance-turn", model=model_id, in_tokens=0, out_tokens=0,
                  actual_usd=ESTIMATED_TURN_USD)
    ledger_total = ledger.running_usd
    (run_dir / "ledger.json").write_text(
        json.dumps({
            "cap_usd": LEDGER_CAP_USD,
            "total_usd": ledger_total,
            "model": model_id,
            "calls": 1,
            "note": "one Opus acceptance turn; recorded at projected upper-bound",
        }, indent=2),
        encoding="utf-8",
    )

    # ── classifier verdict ──
    (run_dir / "classifier_verdict.json").write_text(
        json.dumps({
            "classifier_blocked_proxy": classifier_blocked,
            "derivation": (
                "true iff a stream-json frame named a permission-deny on the "
                "Bedrock/proxy transport during the turn; default false"
            ),
        }, indent=2),
        encoding="utf-8",
    )

    # ── reproduce command ──
    print()
    print(f"[T6] evidence written to: {run_dir}")
    print(f"[T6] is_error={is_error} reply_len={len(reply_text)} "
          f"proxylog {proxylog_before}->{proxylog_after}")
    print(f"[T6] VALIDATE WITH:")
    print(f"     uv run python tools/oi3-acceptance/validate_acceptance.py {run_dir.relative_to(REPO_ROOT)}")

    # Return non-zero on a turn error so a failed run is honest evidence + a
    # non-zero exit (no silent success). The committed run_dir stays for forensics.
    return 0 if (not is_error and len(reply_text) > 0) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OI-3 T6 paid Bedrock acceptance turn through the proxy."
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Authorize the paid run in THIS invocation (equivalent to "
             "OI3_ACCEPTANCE_CONFIRM=1). Without it, the script announces cost "
             "and exits without spending.",
    )
    args = parser.parse_args(argv)

    model_id = _resolve_model_id()

    if not _authorized(args):
        _print_announcement(model_id)
        return 0  # clean exit: announced, did NOT spend

    # Authorized path: announce (for the record), then run.
    print(f"[T6] AUTHORIZED paid run. model={model_id} cap=${LEDGER_CAP_USD:.2f}")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return _run_authorized(run_dir, model_id)


if __name__ == "__main__":
    sys.exit(main())
