# OI-3 Bedrock Auth-Proxy Sidecar — Operational Runbook

This runbook covers pre-demo checks and acceptance steps for the OI-3 Bedrock
auth-proxy sidecar (the containment solution for `AWS_BEARER_TOKEN_BEDROCK`).
It is the T0 deliverable; T6/T8 will extend it with the live acceptance harness.

---

## 1. Bedrock Key Handling

The institutional AWS Bedrock credential is passed to the bridge via the
environment variable `AWS_BEARER_TOKEN_BEDROCK`.  **Key names only are recorded
here; values are never written to any committed file.**

Before the OI-3 sidecar is deployed, `_build_environment`
(`src/dmac_assistant/containers.py`) forwards `AWS_BEARER_TOKEN_BEDROCK` from
the bridge process env directly into every per-user agent container.  After T4
lands, the variable is removed from the container env and the proxy sidecar
holds it instead.

---

## 2. ABSK Key-Expiry Verification Procedure (DD-6 gate)

The OI-3 design assumes the provisioned `AWS_BEARER_TOKEN_BEDROCK` is either
long-lived or set to never expire.  There is no in-proxy refresh logic in the
POC.  **Verify expiration before every demo run** using one of the two methods
below.

### 2a. AWS Management Console

1. Sign in to the AWS console as an admin.
2. Navigate to **IAM → Users** and open the standing IAM user associated with
   the DMAC assistant deployment.
3. Open the **Security credentials** tab.
4. Locate the active **Access key** under "Access keys".
5. Check the **Last used** and **Created** columns; cross-reference against any
   rotation policy.  For ABSK-style bearer tokens, look under **AWS Bedrock**
   service credentials if the console surfaces them separately.
6. If the key shows an expiration date that falls before the demo date, rotate
   or extend it before proceeding.

### 2b. AWS CLI

```bash
# List access keys for the standing IAM user (replace <USERNAME> with the
# actual IAM username):
aws iam list-access-keys --user-name <USERNAME>

# The response includes `CreateDate` and `Status` per key.
# For service-specific credentials (e.g. Bedrock bearer tokens provisioned
# outside IAM access keys), check via the Bedrock console or the provisioning
# source directly.
```

The field to inspect is the **expiration** date (or absence thereof).  If the
key carries no expiration, document this fact in the pre-demo checklist so the
assumption is visible.

---

## 3. Standing IAM User Security Note

The `AWS_BEARER_TOKEN_BEDROCK` credential is associated with a **standing IAM
user** (a long-term credential, not a role or short-lived STS token).  AWS
recommends that long-term keys be used only for exploration and early-stage
development.  The current POC accepts this risk because:

- The credential is held only in the proxy sidecar (post-T4), not in every
  agent container.
- Credential rotation automation is deferred post-POC per the project scope
  boundary (`dmac-assistant-sds.md` §POC vs Post-POC Boundary).

**Action for production:** Replace the standing IAM user credential with an
IAM role + STS assume-role flow before any non-solo deployment.  See
`.claude/known-issues/bedrock-token-exposure.md` for the full risk record.

---

## 4. F2 Network Prerequisite — Start Sidecar Before Proxy

The Bedrock proxy sidecar (`proxy-compose.yml` / `make proxy-up`) declares the
`dmac-nextseek-net` Docker network as **external**.  That network is created by
the NS sidecar stack (`make sidecar-up`).  If the NS sidecar is not running
when you bring the proxy up, Docker Compose will fail with "network not found."

**Pre-flight check (run before `make proxy-up`):**

```bash
# 1. Confirm the network exists:
docker network inspect dmac-nextseek-net

# 2. If the command exits non-zero (network absent), start the NS sidecar first:
make sidecar-up

# 3. Then bring up the proxy:
make proxy-up
```

Do not skip step 1; a missing network causes a silent partial start rather than
an obvious error in some Compose versions.

---

## 5. T0 Baseline Capture

The script `tools/oi3-acceptance/capture_baseline.py` calls `_build_environment`
with a fixture `bridge_env` (placeholder token value — no real secrets) and
writes the resulting env mapping as JSON to
`tools/oi3-acceptance/runs/baseline/build_env_before.txt`.

This committed file is the "before" snapshot for the de-cred diff that T4 will
verify: after T4, `AWS_BEARER_TOKEN_BEDROCK` must NOT appear in the container
env produced by `_build_environment`.

To re-run the baseline capture:

```bash
uv run python tools/oi3-acceptance/capture_baseline.py
```

---

## 6. Running the Acceptance Suite

The live acceptance harness lives under `tools/oi3-acceptance/`.  Two scripts
are involved:

| Script | Role |
|--------|------|
| `tools/oi3-acceptance/run_acceptance.py` | Launches a real Opus turn through the full proxy stack, captures the proxy log, agent env scan, turn transcript, and ledger. |
| `tools/oi3-acceptance/validate_acceptance.py` | Reads the run output dir and asserts all 7 acceptance conditions (token absent from agent env, proxy log grew, model echoed sentinel, classifier did not block proxy, Bedrock streaming intact, ledger within cap, etc.). |

### How the T6 acceptance turn was run

The T6 paid acceptance turn was executed on 2026-06-15 with a $5 hard cap ledger.
Results are committed at `tools/oi3-acceptance/runs/20260615T131344Z/`:

```
agent_env_scan.txt      — confirms AWS_BEARER_TOKEN_BEDROCK absent from agent env
classifier_verdict.json — classifier_blocked_proxy=false
ledger.json             — total_usd=0.25, model=us.anthropic.claude-opus-4-8, calls=1
proxy_log.txt           — proxy log grew (request traversed real proxy)
turn_transcript.jsonl   — model echoed the per-run sentinel
```

**All 7 acceptance conditions: PASS.**

### Reproduce command

Requires the full proxy stack to be running (NS sidecar up first per F2, then
`make proxy-up`) and a live `AWS_BEARER_TOKEN_BEDROCK` in the bridge environment.

```bash
OI3_ACCEPTANCE_CONFIRM=1 uv run python tools/oi3-acceptance/run_acceptance.py
```

The `OI3_ACCEPTANCE_CONFIRM=1` guard prevents accidental paid-API invocations.
After the run completes, validate with:

```bash
uv run python tools/oi3-acceptance/validate_acceptance.py \
    --run-dir tools/oi3-acceptance/runs/<TIMESTAMP>/
```

The validator exits 0 if all 7 conditions pass, non-zero otherwise (with the
failing conditions printed).
