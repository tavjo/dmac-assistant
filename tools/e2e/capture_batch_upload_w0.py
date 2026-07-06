"""Capture W0 NExtSEEK batch-upload fixtures from the live dev API.

The script intentionally loads credentials with python-dotenv and never prints
credential values. It writes committed fixture candidates under
docs/research/fixtures/ns/ and a raw transcript under evidence/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import UTC, datetime
from typing import Any

import httpx
from dotenv import dotenv_values

FIXED_UID = "D.IMG-230913ENG-1757-PUB"
PARENT_UID = "CEL-230912ENG-2-PUB"
COLLISION_TITLE = "Comet Chip Analysis - Data Attached"
COLLISION_IDS = {"351", "260"}
PROJECT_ID = "1"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Recorder:
    def __init__(self, base_url: str, auth: tuple[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, auth=auth, timeout=60)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        name: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.client.request(method, path, params=params, json=json_body)
        call = {
            "name": name,
            "method": method,
            "url": str(response.request.url),
            "path": path,
            "params": params or {},
            "request_json": json_body,
            "status_code": response.status_code,
            "headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "server", "date"}
            },
            "response_text": response.text,
        }
        self.calls.append(call)
        response.raise_for_status()
        return response.json()


def _rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("advanced_search response missing rows[]")
    return rows


def _uid(row: dict[str, Any]) -> str:
    meta = row.get("json_metadata")
    if not isinstance(meta, dict):
        return ""
    uid = meta.get("UID")
    return uid if isinstance(uid, str) else ""


def _project_assay_ids(project_body: dict[str, Any]) -> set[str]:
    rel = project_body["data"]["relationships"]["assays"]["data"]
    return {str(item["id"]) for item in rel}


def _assay_title_map(assays_body: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for item in assays_body.get("data", []):
        title = item.get("attributes", {}).get("title")
        if title:
            out.setdefault(str(title), set()).add(str(item["id"]))
    return out


def _sample_ids(assay_body: dict[str, Any]) -> set[str]:
    rel = assay_body["data"]["relationships"]["samples"]["data"]
    return {str(item["id"]) for item in rel}


def capture(env_file: pathlib.Path, fixtures_dir: pathlib.Path, evidence_dir: pathlib.Path) -> None:
    config = dotenv_values(env_file)
    base = str(config["NEXTSEEK_URL"]).rstrip("/") + "/nextseek_api"
    auth = (str(config["NEXTSEEK_USERNAME"]), str(config["NEXTSEEK_PASSWORD"]))
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    rec = Recorder(base, auth)
    requested = [FIXED_UID, PARENT_UID]
    advanced = rec.request(
        "advanced_search_uid",
        "POST",
        "/samples/advanced_search/",
        params={"page_size": 1000},
        json_body={
            "filter_searchText": requested,
            "searchText_logic": "OR",
            "filter_matchType": "EXACT",
        },
    )
    assays_map = rec.request("assays_map", "GET", "/assays/", params={"page_size": 1000})
    project_assays = rec.request("project_assays", "GET", f"/projects/{PROJECT_ID}/")
    assay_351 = rec.request("assay_samples_351", "GET", "/assays/351/")
    assay_260 = rec.request("assay_samples_260", "GET", "/assays/260/")

    rows = _rows(advanced)
    fixed_rows = [row for row in rows if _uid(row) == FIXED_UID]
    if len(fixed_rows) != 1:
        raise RuntimeError(f"expected exactly one fixed anchor row, found {len(fixed_rows)}")
    fixed = fixed_rows[0]
    numeric_id = fixed.get("id")
    if not isinstance(numeric_id, int):
        raise RuntimeError("fixed anchor row does not carry top-level numeric id")
    assays_str = fixed.get("assays")
    if not isinstance(assays_str, str) or COLLISION_TITLE not in assays_str:
        raise RuntimeError("fixed anchor row lacks required collision assay title")

    title_map = _assay_title_map(assays_map)
    if title_map.get(COLLISION_TITLE) != COLLISION_IDS:
        raise RuntimeError("live assays map no longer resolves collision title to {351,260}")
    project_ids = _project_assay_ids(project_assays)
    if not COLLISION_IDS.issubset(project_ids):
        raise RuntimeError("project 1 no longer contains both collision assay IDs")
    member_ids = _sample_ids(assay_351)
    other_ids = _sample_ids(assay_260)
    if str(numeric_id) not in member_ids or str(numeric_id) in other_ids:
        raise RuntimeError("Path-2 membership anchor is not 351-not-260")

    false_positive_rows = [
        row
        for row in rows
        if _uid(row) not in set(requested)
        and row.get("json_metadata", {}).get("Parent") in set(requested)
    ]
    if not false_positive_rows:
        raise RuntimeError("advanced_search did not produce a Parent false-positive row")

    breadth = sorted(
        {_uid(row) for row in rows if _uid(row)},
        key=lambda uid: next(
            (
                len(str(row.get("assays") or "").split(","))
                for row in rows
                if _uid(row) == uid
            ),
            0,
        ),
        reverse=True,
    )[:10]
    if len(breadth) < 3:
        raise RuntimeError("fewer than three breadth probe UIDs captured")

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "advanced_search_uid.json": advanced,
        "assays_map.json": assays_map,
        "project_assays.json": project_assays,
        "assay_samples_351.json": assay_351,
        "assay_samples_260.json": assay_260,
    }
    for name, body in outputs.items():
        (fixtures_dir / name).write_bytes(_json_bytes(body))

    advanced_bytes = _json_bytes(advanced)
    provenance = {
        "endpoint": "/nextseek_api/samples/advanced_search/",
        "host": base.split("/nextseek_api", 1)[0],
        "capture_date": now,
        "live_probed": True,
        "sha256": _sha256(advanced_bytes),
        "requested_uids": requested,
        "rows": [
            {
                "uid": _uid(row),
                "role": "true_positive" if _uid(row) in set(requested) else "false_positive",
                "synthesized": False,
            }
            for row in rows
        ],
        "probe_sample": {
            "uid": FIXED_UID,
            "numeric_seek_id": numeric_id,
            "collision_title": COLLISION_TITLE,
            "collision_ids": sorted(int(x) for x in COLLISION_IDS),
            "confirmed_project_id": int(PROJECT_ID),
            "membership_assay_id": 351,
            "assays_str_len": len(assays_str),
            "breadth_probe_uids": breadth,
        },
    }
    (fixtures_dir / "advanced_search_uid.provenance.json").write_bytes(_json_bytes(provenance))

    transcript_dir = evidence_dir / now
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript = {
        "capture_date": now,
        "base_url": base,
        "calls": rec.calls,
        "fixture_names": sorted(outputs),
    }
    (transcript_dir / "capture_transcript.json").write_bytes(_json_bytes(transcript))
    print(transcript_dir / "capture_transcript.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env.dev")
    parser.add_argument("--fixtures-dir", default="docs/research/fixtures/ns")
    parser.add_argument("--evidence-dir", default="evidence/batch-upload-w0")
    args = parser.parse_args()
    capture(pathlib.Path(args.env_file), pathlib.Path(args.fixtures_dir), pathlib.Path(args.evidence_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
