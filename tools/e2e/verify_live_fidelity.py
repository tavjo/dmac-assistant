"""Verify the T9.5 read-only NExtSEEK live-fidelity transcript.

The verifier is intentionally transcript-driven: it recomputes every merge-gate
assert from persisted raw HTTP responses and committed fixture anchors. It does
not trust a probe's self-declared pass/fail summary.
"""
from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import dataclass
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "docs" / "research" / "fixtures" / "ns"
TRUNCATION_THRESHOLD = 900
REQUIRED_CHECKS = {"structure", "name_check", "dag"}
DEV_HOST = "nextseek-dev.mit.edu"


class VerificationError(Exception):
    """Raised when a transcript fails a T9.5 gate assertion."""


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    endpoint: str
    host: str
    status_code: int
    response_json: Any
    request_json: Any | None = None
    request_form: dict[str, Any] | None = None


def verify(path: str | pathlib.Path) -> dict[str, Any]:
    transcript = _load_json(pathlib.Path(path))
    provenance = _load_json(FIXTURE_DIR / "advanced_search_uid.provenance.json")
    if _contains_key(provenance, "authoritative_assay_ids"):
        raise VerificationError("provenance must not contain authoritative_assay_ids")

    calls = _calls_by_name(transcript)
    probe = provenance["probe_sample"]
    uid = str(probe["uid"])
    collision_title = str(probe["collision_title"])
    collision_ids = {int(item) for item in probe["collision_ids"]}
    member = int(probe["membership_assay_id"])
    project_id = int(probe["confirmed_project_id"])
    numeric_id = int(probe["numeric_seek_id"])

    _cross_check_anchor(collision_title, collision_ids, numeric_id)

    advanced = _single_row(_call(calls, "advanced_search_uid").response_json, uid)
    live_assays = str(advanced.get("assays") or "")
    live_numeric_id = int(advanced.get("id"))
    if live_numeric_id != numeric_id:
        raise VerificationError("advanced_search numeric id drifted from canonical anchor")
    if len(live_assays) >= TRUNCATION_THRESHOLD:
        raise VerificationError("probe assays string is truncation-suspect")

    assays_call = _call(calls, "assays_map")
    title_map = _title_map(assays_call.response_json)
    fixture_titles = set(_fixture_titles(uid, title_map))
    live_titles = set(_parse_titles(live_assays, title_map))
    if live_titles != fixture_titles:
        raise VerificationError("live assays titles differ from committed fixture")
    if collision_title not in live_titles:
        raise VerificationError("collision title absent from live probe row")

    project_ids = _project_ids(_call(calls, "project_assays").response_json)
    if project_id != int(transcript.get("project_confirmation", {}).get("project_id", project_id)):
        raise VerificationError("project confirmation does not match probe project")
    resolved = _resolve_titles(
        live_titles,
        title_map=title_map,
        project_ids=project_ids,
        sample_numeric_id=numeric_id,
        assay_samples={
            int(assay_id): _sample_ids(_call(calls, f"assay_samples_{assay_id}").response_json)
            for assay_id in sorted(collision_ids)
        },
    )

    auth_call = _call(calls, "sample_detail")
    auth_set = _authoritative_assays(auth_call.response_json)
    if transcript.get("auth_set_source") != "sample_detail":
        raise VerificationError("AUTH_SET must be sourced from sample_detail")
    if auth_set != resolved:
        raise VerificationError(f"resolved assays {sorted(resolved)} != AUTH_SET {sorted(auth_set)}")
    if member not in resolved or (collision_ids - {member}) & resolved:
        raise VerificationError("duplicate-title Path-2 membership resolved to the wrong candidate")

    validate = _call(calls, "delivered_workbook_validate")
    _assert_validate(validate, int(transcript.get("delivered_workbook", {}).get("row_count", -1)))
    _assert_breadth(_call(calls, "breadth_advanced_search"), title_map)

    return {
        "uid": uid,
        "auth_set": sorted(auth_set),
        "resolved": sorted(resolved),
        "breadth_rows": len(_rows(_call(calls, "breadth_advanced_search").response_json)),
    }


def _cross_check_anchor(collision_title: str, collision_ids: set[int], numeric_id: int) -> None:
    import importlib.util

    anchor_path = REPO_ROOT / "tests" / "unit" / "fixtures" / "ns" / "duplicate_title_anchor.py"
    spec = importlib.util.spec_from_file_location("duplicate_title_anchor", anchor_path)
    if spec is None or spec.loader is None:
        raise VerificationError("duplicate title anchor is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.COLLISION_TITLE != collision_title:
        raise VerificationError("collision title drifted from canonical constants")
    if {int(item) for item in module.COLLISION_IDS} != collision_ids:
        raise VerificationError("collision ids drifted from canonical constants")
    if int(module.PROBE_NUMERIC_SEEK_ID) != numeric_id:
        raise VerificationError("numeric seek id drifted from canonical constants")


def _assert_validate(call: Call, row_count: int) -> None:
    body = call.response_json
    if not isinstance(body, dict):
        raise VerificationError("validate response is not an object")
    if not body.get("valid"):
        raise VerificationError("delivered workbook validate returned invalid")
    if set(body.get("checks_run") or []) < REQUIRED_CHECKS:
        raise VerificationError("delivered workbook validate missed required checks")
    processed = (body.get("totals") or {}).get("processed")
    if row_count < 1 or int(processed or -1) != row_count:
        raise VerificationError("delivered workbook validate processed count mismatch")
    form = call.request_form or {}
    if form.get("checks") != "structure,name_check,dag":
        raise VerificationError("validate request did not send checks as multipart form field")


def _assert_breadth(call: Call, title_map: dict[str, list[int]]) -> None:
    rows = _rows(call.response_json)
    if len(rows) < 3:
        raise VerificationError("breadth probe returned fewer than three rows")
    for row in rows:
        assays = str(row.get("assays") or "")
        if len(assays) >= TRUNCATION_THRESHOLD:
            raise VerificationError("breadth row assays string is truncation-suspect")
        _parse_titles(assays, title_map)


def _resolve_titles(
    titles: set[str],
    *,
    title_map: dict[str, list[int]],
    project_ids: set[int],
    sample_numeric_id: int,
    assay_samples: dict[int, set[str]],
) -> set[int]:
    resolved: set[int] = set()
    for title in titles:
        candidates = [int(item) for item in title_map.get(title, [])]
        if not candidates:
            raise VerificationError(f"title not in live assay map: {title}")
        narrowed = [item for item in candidates if item in project_ids]
        if not narrowed:
            raise VerificationError(f"title not in project assays: {title}")
        if len(narrowed) == 1:
            resolved.add(narrowed[0])
            continue
        matched = {item for item in narrowed if str(sample_numeric_id) in assay_samples.get(item, set())}
        if not matched:
            raise VerificationError(f"Path-2 failed to resolve: {title}")
        resolved.update(matched)
    return resolved


def _fixture_titles(uid: str, title_map: dict[str, list[int]]) -> list[str]:
    row = _single_row(_load_json(FIXTURE_DIR / "advanced_search_uid.json"), uid)
    return _parse_titles(str(row.get("assays") or ""), title_map)


def _parse_titles(raw: str, title_map: dict[str, list[int]]) -> list[str]:
    titles = sorted(title_map, key=len, reverse=True)
    parsed: list[str] = []
    pos = 0
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in {",", " "}:
            pos += 1
        if pos >= len(raw):
            break
        match = next((title for title in titles if raw.startswith(title, pos)), None)
        if match is None:
            raise VerificationError(f"could not parse assay titles: {raw}")
        end = pos + len(match)
        if end < len(raw) and raw[end] not in {",", " "}:
            raise VerificationError(f"could not parse assay titles: {raw}")
        parsed.append(match)
        pos = end
    return parsed


def _calls_by_name(transcript: dict[str, Any]) -> dict[str, Call]:
    calls: dict[str, Call] = {}
    for raw in transcript.get("calls", []):
        call = _call_from_raw(raw)
        if call.name in calls:
            raise VerificationError(f"duplicate call name: {call.name}")
        calls[call.name] = call
    return calls


def _call_from_raw(raw: dict[str, Any]) -> Call:
    for key in ("name", "method", "endpoint", "host", "status_code"):
        if key not in raw:
            raise VerificationError(f"call missing {key}")
    response_json = raw["response_json"] if "response_json" in raw else _parse_response_text(raw.get("response_text"))
    call = Call(
        name=str(raw["name"]),
        method=str(raw["method"]).upper(),
        endpoint=str(raw["endpoint"]),
        host=str(raw["host"]),
        status_code=int(raw["status_code"]),
        response_json=response_json,
        request_json=raw.get("request_json"),
        request_form=raw.get("request_form"),
    )
    if call.status_code >= 400:
        raise VerificationError(f"{call.name} returned HTTP {call.status_code}")
    if call.host != DEV_HOST:
        raise VerificationError(f"{call.name} host {call.host!r} is not {DEV_HOST!r}")
    if not call.endpoint.startswith("/nextseek_api/"):
        raise VerificationError(f"{call.name} endpoint is not a NExtSEEK API path")
    return call


def _call(calls: dict[str, Call], name: str) -> Call:
    try:
        return calls[name]
    except KeyError as exc:
        raise VerificationError(f"missing raw call: {name}") from exc


def _parse_response_text(text: Any) -> Any:
    if not isinstance(text, str):
        raise VerificationError("call missing response_json/response_text")
    return json.loads(text)


def _rows(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
        raise VerificationError("advanced_search response missing rows")
    return body["rows"]


def _single_row(body: Any, uid: str) -> dict[str, Any]:
    matches = [row for row in _rows(body) if _metadata_uid(row) == uid]
    if len(matches) != 1:
        raise VerificationError(f"expected exactly one row for {uid}, found {len(matches)}")
    return matches[0]


def _metadata_uid(row: dict[str, Any]) -> str:
    meta = row.get("json_metadata")
    if isinstance(meta, str):
        meta = json.loads(meta)
    return str(meta.get("UID") or "") if isinstance(meta, dict) else ""


def _title_map(body: Any) -> dict[str, list[int]]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise VerificationError("assays map response missing data")
    out: dict[str, list[int]] = {}
    for item in body["data"]:
        title = ((item.get("attributes") or {}).get("title")) if isinstance(item, dict) else None
        if title:
            out.setdefault(str(title), []).append(int(item["id"]))
    if not out:
        raise VerificationError("assays map response contained no assay titles")
    for ids in out.values():
        ids.sort()
    return out


def _project_ids(body: Any) -> set[int]:
    rel = body["data"]["relationships"]["assays"]["data"]
    return {int(item["id"]) for item in rel}


def _sample_ids(body: Any) -> set[str]:
    rel = body["data"]["relationships"]["samples"]["data"]
    return {str(item["id"]) for item in rel}


def _authoritative_assays(body: Any) -> set[int]:
    rel = body["data"]["relationships"]["assays"]["data"]
    return {int(item["id"]) for item in rel}


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript")
    args = parser.parse_args(argv)
    try:
        result = verify(args.transcript)
    except VerificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
