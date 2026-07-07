"""$0 independent verifier for a T10 live paid batch-upload E2E bundle.

Recomputes the verdict + cost from the persisted transcript ONLY (never trusting the driver's
self-declared summary), cross-checks the persisted summary against the recompute (tamper
detection), and enforces "markdown is never proof" — the bundle must carry machine-readable JSON
evidence (the transcript + a ledger), not only prose. Exits non-zero on any failure.

Usage:
    uv run python tools/e2e/verify_batch_upload_live.py evidence/batch-upload-e2e/<ts>/live_e2e_transcript.json

This is the reproducible cross-session check: given a committed transcript, anyone can re-derive
the cost and verdict deterministically.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.e2e.batch_upload_live_evidence import (  # noqa: E402
    build_summary,
    detect_error,
    evaluate_turn,
    extract_cost,
    session_ended_frames,
)

_COST_TOL = 1e-9
# The POLICY cap is enforced HERE as a constant — the verifier must NOT let the artifact under
# test set its own ceiling via meta.cap_usd (fix H1). An operator may only TIGHTEN it via --cap.
POLICY_CAP_USD = 5.00
_RECONCILE_TOL = 1e-6


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(
    transcript_path: pathlib.Path, *, policy_cap_usd: float = POLICY_CAP_USD
) -> dict[str, Any]:
    problems: list[str] = []
    bundle = transcript_path.parent

    if not transcript_path.exists():
        return {"ok": False, "problems": [f"transcript not found: {transcript_path}"]}
    data = _load(transcript_path)
    frames = data.get("frames")
    if not isinstance(frames, list):
        return {"ok": False, "problems": ["transcript has no 'frames' list"]}
    meta = data.get("meta") or {}
    query = meta.get("query", "")
    # The cap is the VERIFIER's policy constant, NOT the artifact's self-declared meta.cap_usd
    # (fix H1). A bundle that declares a looser cap than policy is itself a red flag.
    declared_cap = meta.get("cap_usd")
    if isinstance(declared_cap, (int, float)) and float(declared_cap) > policy_cap_usd:
        problems.append(
            f"bundle declares cap ${float(declared_cap):.2f} > policy cap ${policy_cap_usd:.2f}"
        )

    # "Markdown is never proof": the bundle must carry machine-readable JSON evidence.
    ledger_path = bundle / "ledger.jsonl"
    summary_path = bundle / "per_turn_summary.json"
    if not ledger_path.exists():
        problems.append("missing ledger.jsonl (markdown is never proof)")
    if not summary_path.exists():
        problems.append("missing per_turn_summary.json")
    json_evidence = [p for p in bundle.iterdir() if p.suffix in {".json", ".jsonl"}]
    if not json_evidence:
        problems.append("bundle carries no .json/.jsonl evidence — prose is not proof")

    # A decoy cheap result frame before the real one would mask the true cost (M2).
    if len(session_ended_frames(frames)) > 1:
        problems.append(
            f"transcript carries {len(session_ended_frames(frames))} session_ended frames "
            "(expected exactly one terminal result)"
        )

    # Recompute the verdict + AUTHORITATIVE cost from the transcript alone.
    is_error = detect_error(frames)
    row = evaluate_turn(query=query, frames=frames, is_error=is_error)
    cost = extract_cost(frames)
    authoritative_cost = cost.cost_usd

    # Ledger total from the persisted ledger (settled actual_usd sum).
    ledger_total = 0.0
    ledger_present = ledger_path.exists()
    if ledger_present:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("status") == "settled" and entry.get("actual_usd") is not None:
                ledger_total += float(entry["actual_usd"])

    # Reconcile the driver-written ledger against the turn's own authoritative cost — a ledger
    # that understates a real spend (or a reserved-only/crashed ledger recording $0 for a paid
    # turn) is caught here (fix H2 + M1).
    if ledger_present and abs(ledger_total - authoritative_cost) > _RECONCILE_TOL:
        problems.append(
            f"ledger total ${ledger_total:.6f} != authoritative transcript cost "
            f"${authoritative_cost:.6f} (cost_source={cost.cost_source})"
        )

    # Cap-check the REAL spend (the larger of the authoritative figure and the ledger) against
    # the policy cap — not the artifact's self-declared cap (fix H2).
    real_spend = max(ledger_total, authoritative_cost)
    if real_spend > policy_cap_usd:
        problems.append(
            f"spend ${real_spend:.6f} exceeds policy cap ${policy_cap_usd:.2f}"
        )

    aborted = bool(meta.get("reserved_only"))
    recomputed = build_summary(
        row, ledger_total_usd=ledger_total, cap_usd=policy_cap_usd, aborted_on_budget=aborted
    )

    if not row.passed:
        problems.extend(f"verdict: {p}" for p in row.problems)

    # Tamper detection: the persisted summary must agree with the recompute.
    if summary_path.exists():
        persisted = _load(summary_path)
        p_turn = persisted.get("turn", {})
        if abs(float(p_turn.get("cost_usd", -1)) - authoritative_cost) > _COST_TOL:
            problems.append(
                f"persisted cost_usd={p_turn.get('cost_usd')} != recomputed {authoritative_cost}"
            )
        if bool(persisted.get("all_pass")) != bool(recomputed["all_pass"]):
            problems.append(
                f"persisted all_pass={persisted.get('all_pass')} != recomputed "
                f"{recomputed['all_pass']}"
            )
        if p_turn.get("validate_invoked") != row.validate_invoked:
            problems.append(
                f"persisted validate_invoked={p_turn.get('validate_invoked')} != recomputed "
                f"{row.validate_invoked}"
            )

    ok = not problems
    return {
        "ok": ok,
        "problems": problems,
        "recomputed": recomputed,
        "cost_source": cost.cost_source,
        "ledger_total_usd": ledger_total,
        "authoritative_cost_usd": authoritative_cost,
        "policy_cap_usd": policy_cap_usd,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=pathlib.Path)
    parser.add_argument(
        "--cap", type=float, default=POLICY_CAP_USD,
        help=f"Policy spend cap in USD to enforce (default {POLICY_CAP_USD}; may only tighten).",
    )
    args = parser.parse_args(argv)
    cap = min(args.cap, POLICY_CAP_USD)  # an operator may tighten, never loosen, the policy cap
    result = verify(args.transcript, policy_cap_usd=cap)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
