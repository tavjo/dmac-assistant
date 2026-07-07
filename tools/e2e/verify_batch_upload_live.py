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
)

_COST_TOL = 1e-9


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(transcript_path: pathlib.Path) -> dict[str, Any]:
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
    cap_usd = float(meta.get("cap_usd", 5.00))

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

    # Recompute the verdict from the transcript alone.
    is_error = detect_error(frames)
    row = evaluate_turn(query=query, frames=frames, is_error=is_error)
    cost = extract_cost(frames)

    # Ledger total from the persisted ledger (settled actual_usd sum), else the recomputed cost.
    ledger_total = cost.cost_usd
    if ledger_path.exists():
        settled = 0.0
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("status") == "settled" and entry.get("actual_usd") is not None:
                settled += float(entry["actual_usd"])
        ledger_total = settled

    recomputed = build_summary(
        row, ledger_total_usd=ledger_total, cap_usd=cap_usd, aborted_on_budget=False
    )

    if not row.passed:
        problems.extend(f"verdict: {p}" for p in row.problems)
    if not recomputed["within_cap"]:
        problems.append(
            f"ledger total ${ledger_total:.6f} exceeds cap ${cap_usd:.2f}"
        )

    # Tamper detection: the persisted summary must agree with the recompute.
    if summary_path.exists():
        persisted = _load(summary_path)
        p_turn = persisted.get("turn", {})
        if abs(float(p_turn.get("cost_usd", -1)) - cost.cost_usd) > _COST_TOL:
            problems.append(
                f"persisted cost_usd={p_turn.get('cost_usd')} != recomputed {cost.cost_usd}"
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=pathlib.Path)
    args = parser.parse_args(argv)
    result = verify(args.transcript)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
