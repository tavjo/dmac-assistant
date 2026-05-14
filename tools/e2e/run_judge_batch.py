#!/usr/bin/env python3
"""Loop tools.e2e.evaluate.judge_query over every .record.json in an
evidence dir and write judged copies + a summary.

Adapter for batches that aren't exactly 10 records (the canonical
aggregate() asserts exactly 10).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.e2e.evaluate import judge_query  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True,
                    help="dir with .record.json + queries.json")
    ap.add_argument("--output-dir", required=True,
                    help="dir to write .judged.json + summary.json")
    ap.add_argument("--image", required=True)
    args = ap.parse_args()

    in_dir = Path(args.input_dir).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    records = sorted(in_dir.glob("*.record.json"))
    print(f"[judge] {len(records)} records  image={args.image}", flush=True)

    summary = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "image": args.image, "input_dir": str(in_dir),
               "verdicts": [], "counts": {}}

    for i, rp in enumerate(records, 1):
        t0 = time.time()
        judged = judge_query(record_path=rp, image_tag=args.image,
                             evidence_dir=in_dir, out_dir=out_dir)
        dt = time.time() - t0
        v = judged.judge_verdict or "none"
        out_path = out_dir / rp.name.replace(".record.json", ".judged.json")
        out_path.write_text(judged.model_dump_json(indent=2))
        summary["verdicts"].append({"id": judged.query_id,
                                    "verdict": v,
                                    "latency_s": round(dt, 1)})
        summary["counts"][v] = summary["counts"].get(v, 0) + 1
        print(f"[{i}/{len(records)}] {judged.query_id:<28} -> {v:<12} {dt:5.1f}s",
              flush=True)

    summary["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n[judge] verdict counts:", summary["counts"])
    print(f"[judge] summary: {out_dir/'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
