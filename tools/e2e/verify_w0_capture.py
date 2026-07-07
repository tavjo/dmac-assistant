"""Verify W0 committed fixtures against a raw HTTP capture transcript."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

EXPECTED = {
    "advanced_search_uid": "advanced_search_uid.json",
    "assays_map": "assays_map.json",
    "project_assays": "project_assays.json",
    "assay_samples_351": "assay_samples_351.json",
    "assay_samples_260": "assay_samples_260.json",
}
COLLISION_TITLE = "Comet Chip Analysis - Data Attached"
COLLISION_IDS = {"351", "260"}
FIXED_UID = "D.IMG-230913ENG-1757-PUB"
PARENT_UID = "CEL-230912ENG-2-PUB"


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _response_json(call: dict[str, Any]) -> Any:
    if int(call.get("status_code", 0)) >= 400:
        raise ValueError(f"{call.get('name')} returned HTTP {call.get('status_code')}")
    return json.loads(call["response_text"])


def _rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("advanced_search body missing rows[]")
    return rows


def _uid(row: dict[str, Any]) -> str:
    uid = row.get("json_metadata", {}).get("UID")
    return uid if isinstance(uid, str) else ""


def _title_map(body: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for item in body.get("data", []):
        title = item.get("attributes", {}).get("title")
        if title:
            out.setdefault(str(title), set()).add(str(item["id"]))
    return out


def _project_assay_ids(body: dict[str, Any]) -> set[str]:
    return {str(item["id"]) for item in body["data"]["relationships"]["assays"]["data"]}


def _sample_ids(body: dict[str, Any]) -> set[str]:
    return {str(item["id"]) for item in body["data"]["relationships"]["samples"]["data"]}


def _expected_breadth(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {_uid(row) for row in rows if _uid(row)},
        key=lambda uid: (
            -next(
                (
                    len(str(row.get("assays") or "").split(","))
                    for row in rows
                    if _uid(row) == uid
                ),
                0,
            ),
            uid,
        ),
    )[:10]


def verify(transcript_path: pathlib.Path, fixtures_dir: pathlib.Path) -> None:
    transcript = _load_json(transcript_path)
    calls = {call["name"]: call for call in transcript.get("calls", [])}
    missing = sorted(set(EXPECTED) - set(calls))
    if missing:
        raise SystemExit(f"missing transcript calls: {missing}")

    recomputed = {name: _response_json(calls[name]) for name in EXPECTED}
    for call_name, fixture_name in EXPECTED.items():
        fixture = fixtures_dir / fixture_name
        if _canonical(recomputed[call_name]) != fixture.read_bytes():
            raise SystemExit(f"fixture does not match transcript response: {fixture_name}")

    advanced = recomputed["advanced_search_uid"]
    assays_map = recomputed["assays_map"]
    project = recomputed["project_assays"]
    assay_351 = recomputed["assay_samples_351"]
    assay_260 = recomputed["assay_samples_260"]

    rows = _rows(advanced)
    advanced_call = calls["advanced_search_uid"]
    request = advanced_call.get("request_json")
    expected_requested = [FIXED_UID, PARENT_UID]
    if request != {
        "filter_searchText": expected_requested,
        "searchText_logic": "OR",
        "filter_matchType": "EXACT",
    }:
        raise SystemExit("advanced_search request body does not match W0 contract")
    if "attribute" in request:
        raise SystemExit("advanced_search request unexpectedly contains attribute")

    fixed = [row for row in rows if _uid(row) == FIXED_UID]
    if len(fixed) != 1:
        raise SystemExit("fixed anchor row missing or duplicated")
    fixed_row = fixed[0]
    numeric_id = fixed_row.get("id")
    assays_str = fixed_row.get("assays")
    if not isinstance(numeric_id, int):
        raise SystemExit("fixed anchor row lacks numeric id")
    if not isinstance(assays_str, str) or COLLISION_TITLE not in assays_str:
        raise SystemExit("fixed anchor assays field does not contain collision title")
    if _title_map(assays_map).get(COLLISION_TITLE) != COLLISION_IDS:
        raise SystemExit("assays map does not reproduce collision IDs")
    if not COLLISION_IDS.issubset(_project_assay_ids(project)):
        raise SystemExit("project fixture does not contain both collision assay IDs")
    if str(numeric_id) not in _sample_ids(assay_351) or str(numeric_id) in _sample_ids(assay_260):
        raise SystemExit("membership fixture is not 351-not-260")

    provenance_path = fixtures_dir / "advanced_search_uid.provenance.json"
    provenance = _load_json(provenance_path)
    transcript_host = str(transcript.get("base_url", "")).split("/nextseek_api", 1)[0]
    expected_rows = [
        {
            "uid": _uid(row),
            "role": "true_positive" if _uid(row) in set(expected_requested) else "false_positive",
            "synthesized": False,
        }
        for row in rows
    ]
    if provenance.get("endpoint") != "/nextseek_api/samples/advanced_search/":
        raise SystemExit("provenance endpoint mismatch")
    if provenance.get("host") != transcript_host:
        raise SystemExit("provenance host is not transcript-derived")
    if provenance.get("capture_date") != transcript.get("capture_date"):
        raise SystemExit("provenance capture_date is not transcript-derived")
    if provenance.get("live_probed") is not True:
        raise SystemExit("provenance live_probed must be true")
    if provenance.get("requested_uids") != expected_requested:
        raise SystemExit("provenance requested_uids mismatch")
    if provenance.get("rows") != expected_rows:
        raise SystemExit("provenance rows are not transcript-derived")
    if provenance.get("sha256") != _sha256(_canonical(advanced)):
        raise SystemExit("provenance sha256 does not match transcript-derived advanced_search")
    probe = provenance.get("probe_sample", {})
    expected_probe = {
        "uid": FIXED_UID,
        "numeric_seek_id": numeric_id,
        "collision_title": COLLISION_TITLE,
        "collision_ids": [260, 351],
        "confirmed_project_id": 1,
        "membership_assay_id": 351,
        "assays_str_len": len(assays_str),
    }
    for key, expected in expected_probe.items():
        if probe.get(key) != expected:
            raise SystemExit(f"provenance probe_sample.{key} mismatch")
    if probe.get("breadth_probe_uids") != _expected_breadth(rows):
        raise SystemExit("provenance breadth_probe_uids mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript")
    parser.add_argument("fixtures_dir")
    args = parser.parse_args()
    verify(pathlib.Path(args.transcript), pathlib.Path(args.fixtures_dir))
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
