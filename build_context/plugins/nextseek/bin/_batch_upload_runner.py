"""NExtSEEK batch-upload runner and hard delivery gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import os
import shutil
import sys
import tempfile
from typing import Any

import orjson
import polars as pl

from _batch_upload_client import BatchUploadClient
from _batch_upload_extract import extract_text
from _batch_upload_payload import build as build_payload

REQUIRED_CHECKS = {"structure", "name_check", "dag"}
SCRATCH_ROOT = pathlib.Path("/data/scratch")
TRUNCATION_THRESHOLD = 900


class GateError(Exception):
    def __init__(self, gate: str, detail: str = "") -> None:
        super().__init__(gate)
        self.gate = gate
        self.detail = detail


def _emit_gate(exc: GateError) -> None:
    payload = {"gate": exc.gate}
    if exc.detail:
        payload["detail"] = exc.detail
    print(json.dumps(payload, separators=(",", ":")))


def _client(transport=None) -> BatchUploadClient:
    if transport is not None and hasattr(transport, "validate_file"):
        return transport
    return BatchUploadClient.from_env(transport=transport)


def _load_rows(path: str | pathlib.Path) -> list[dict[str, Any]]:
    rows = json.loads(pathlib.Path(path).read_text())
    if not isinstance(rows, list):
        raise GateError("rows")
    return rows


def _read_confirmation(path: str | pathlib.Path | None, project_id: int) -> dict[str, Any]:
    if path is None:
        raise GateError("project_unconfirmed")
    token = json.loads(pathlib.Path(path).read_text())
    accessible = {int(item) for item in token.get("accessible_project_ids", [])}
    if not token.get("confirmed") or int(token.get("project_id", -1)) != project_id:
        raise GateError("project_unconfirmed")
    if project_id not in accessible:
        raise GateError("project_unconfirmed")
    return token


def _schema_for_rows(client: BatchUploadClient, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for sample_type in sorted({str(row.get("SampleType") or "") for row in rows}):
        if not sample_type:
            raise GateError("schema")
        schema = client.sample_type_attributes(sample_type)
        attrs = schema.get("attributes")
        if not isinstance(attrs, list) or not attrs:
            raise GateError("schema")
        if not all(isinstance(item, dict) and item.get("title") for item in attrs):
            raise GateError("schema")
        if not any("required" in item or "is_title" in item for item in attrs):
            raise GateError("schema")
        schemas.append(schema)
    return schemas


def _has_non_uid_value(row: dict[str, Any]) -> bool:
    attrs = row.get("attributes") or {}
    return any(key != "UID" and not _blank(value) for key, value in attrs.items())


def _is_update(row: dict[str, Any]) -> bool:
    return bool(str(row.get("UID") or "").strip())


def _assay_touching(row: dict[str, Any]) -> bool:
    return _is_update(row) and bool(row.get("assay_ids") or row.get("assay_titles"))


def _preflight_non_empty(rows: list[dict[str, Any]]) -> None:
    if not rows or not any(_has_non_uid_value(row) or row.get("assay_ids") or row.get("assay_titles") for row in rows):
        raise GateError("non_empty")


def _assay_maps(client: BatchUploadClient, project_id: int) -> tuple[dict[str, list[int]], set[int], dict[int, str]]:
    title_map = client.list_assays()
    project_ids = client.project_assays(project_id)
    id_to_title: dict[int, str] = {}
    for title, ids in title_map.items():
        for assay_id in ids:
            id_to_title[int(assay_id)] = title
    return title_map, project_ids, id_to_title


def _resolve_additions(
    rows: list[dict[str, Any]],
    client: BatchUploadClient,
    title_map: dict[str, list[int]],
    project_ids: set[int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        ids = {int(item) for item in copy.get("assay_ids") or []}
        for title in copy.get("assay_titles") or []:
            ids.add(client.resolve_assay_title(str(title), title_map, project_ids))
        copy["assay_ids"] = sorted(ids)
        out.append(copy)
    return out


def _resolve_manifest(
    rows: list[dict[str, Any]],
    client: BatchUploadClient,
    title_map: dict[str, list[int]],
    project_ids: set[int],
) -> dict[str, dict[str, Any]]:
    uids = sorted({str(row.get("UID")).strip() for row in rows if _is_update(row)})
    if not uids:
        return {}
    by_uid = {
        row.get("json_metadata", {}).get("UID"): row
        for row in client.search_samples_by_uid(uids, known_assay_titles=title_map.keys())
        if isinstance(row.get("json_metadata"), dict)
    }
    manifest: dict[str, dict[str, Any]] = {}
    for uid in uids:
        found = by_uid.get(uid)
        if found is None:
            manifest[uid] = {"current_assay_ids": None, "retrieve_status": "absent"}
            continue
        raw_assays = found.get("assays")
        if raw_assays is None:
            manifest[uid] = {"current_assay_ids": None, "retrieve_status": "degraded"}
            continue
        if len(str(raw_assays)) >= TRUNCATION_THRESHOLD:
            manifest[uid] = {"current_assay_ids": None, "retrieve_status": "degraded"}
            continue
        try:
            titles = list(found.get("assay_titles") or [])
            current = client.resolve_current_assay_titles(
                titles,
                sample_numeric_id=found["numeric_seek_id"],
                title_map=title_map,
                project_assay_ids=project_ids,
            )
        except Exception:
            manifest[uid] = {"current_assay_ids": None, "retrieve_status": "degraded"}
        else:
            manifest[uid] = {
                "current_assay_ids": sorted(int(item) for item in current),
                "retrieve_status": "verified",
            }
    return manifest


def _verified_current(manifest: dict[str, dict[str, Any]]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for uid, entry in manifest.items():
        if entry.get("retrieve_status") == "verified":
            out[uid] = {int(item) for item in entry.get("current_assay_ids") or []}
    return out


def _write_manifest(path: pathlib.Path, manifest: dict[str, dict[str, Any]]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _read_rows_from_xlsx(path: pathlib.Path) -> list[dict[str, Any]]:
    df = pl.read_excel(str(path), sheet_name="Samples", engine="calamine")
    rows: list[dict[str, Any]] = []
    for idx in range(df.height):
        rows.append({column: df[column][idx] for column in df.columns})
    return rows


def _artifact_gate(
    *,
    artifact: pathlib.Path,
    validation: dict[str, Any],
    manifest: dict[str, dict[str, Any]],
    confirm_clear_assays: set[str] | None = None,
) -> None:
    confirm_clear_assays = confirm_clear_assays or set()
    rows = _read_rows_from_xlsx(artifact)
    if not validation.get("valid"):
        raise GateError("server_valid")
    if set(validation.get("checks_run") or []) < REQUIRED_CHECKS:
        raise GateError("checks_run")
    processed = ((validation.get("totals") or {}).get("processed"))
    if processed is None or int(processed) != len(rows):
        raise GateError("processed")

    for row in rows:
        metadata = orjson.loads(row["json_metadata"] or "{}")
        uid = str(row.get("UID") or metadata.get("UID") or "").strip()
        assay_ids = set(orjson.loads(row.get("assay_ids") or "[]"))
        real_attrs = {k: v for k, v in metadata.items() if k != "UID" and not _blank(v)}
        if uid:
            for key, value in metadata.items():
                if key != "UID" and _blank(value):
                    raise GateError("present_blank", key)
        elif not real_attrs:
            raise GateError("required_missing")
        if uid and uid not in manifest:
            raise GateError("manifest")
        if uid and uid in manifest:
            entry = manifest[uid]
            if entry.get("retrieve_status") != "verified":
                raise GateError("manifest")
            current = set(entry.get("current_assay_ids") or [])
            if not current <= assay_ids and uid not in confirm_clear_assays:
                raise GateError("assay_superset")
        clear_assays = uid in confirm_clear_assays and bool((manifest.get(uid) or {}).get("current_assay_ids"))
        if not real_attrs and not assay_ids and not clear_assays:
            raise GateError("non_empty")


def _promote(staged: pathlib.Path, output_dir: pathlib.Path) -> pathlib.Path:
    if SCRATCH_ROOT in staged.parents:
        raise GateError("staging")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / staged.name
    tmp_target = output_dir / f".{staged.name}.tmp"
    shutil.copy2(staged, tmp_target)
    if _sha256(staged) != _sha256(tmp_target):
        raise GateError("promote_hash")
    os.replace(tmp_target, target)
    return target


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cmd_attrs(argv: list[str], *, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="nextseek-sampletype-attrs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--type")
    group.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    client = _client(transport)
    print(json.dumps(client.list_sample_types() if args.list else client.sample_type_attributes(args.type)))
    return 0


def _cmd_extract(argv: list[str], *, transport=None) -> int:
    del transport
    parser = argparse.ArgumentParser(prog="nextseek-extract-text")
    parser.add_argument("--file", required=True)
    parser.add_argument("--fallback")
    args = parser.parse_args(argv)
    print(extract_text(args.file, fallback=args.fallback))
    return 0


def _cmd_project_resolve(argv: list[str], *, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="nextseek-project-resolve")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    client = _client(transport)
    projects = client.list_projects()
    accessible = [int(item["id"]) for item in projects]
    token = {
        "project_id": args.project_id,
        "accessible_project_ids": accessible,
        "confirmed": bool(args.confirmed and args.project_id in accessible),
    }
    pathlib.Path(args.out).write_text(json.dumps(token, indent=2))
    print(json.dumps(token))
    return 0 if token["confirmed"] else 1


def _cmd_assay_resolve(argv: list[str], *, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="nextseek-assay-resolve")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--title", action="append", required=True)
    args = parser.parse_args(argv)
    client = _client(transport)
    title_map, project_ids, _ = _assay_maps(client, args.project_id)
    result = {title: client.resolve_assay_title(title, title_map, project_ids) for title in args.title}
    print(json.dumps(result, sort_keys=True))
    return 0


def _cmd_sample_search(argv: list[str], *, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="nextseek-sample-search")
    parser.add_argument("--uid", action="append", required=True, dest="uids")
    args = parser.parse_args(argv)
    print(json.dumps(_client(transport).search_samples_by_uid(args.uids)))
    return 0


def _cmd_build_payload(argv: list[str], *, transport=None) -> int:
    del transport
    parser = argparse.ArgumentParser(prog="nextseek-build-payload")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--resolved-current")
    parser.add_argument("--id-to-title", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = pathlib.Path(args.out)
    if SCRATCH_ROOT in out.parents or out == SCRATCH_ROOT:
        raise GateError("staging")
    rows = _load_rows(args.rows)
    schema = json.loads(pathlib.Path(args.schema).read_text())
    resolved = _load_current(args.resolved_current)
    id_to_title = {int(k): v for k, v in json.loads(pathlib.Path(args.id_to_title).read_text()).items()}
    for path in build_payload(rows, out, resolved_current=resolved, id_to_title=id_to_title, sample_type_attributes=schema):
        print(path)
    return 0


def _cmd_build_validate(argv: list[str], *, transport=None) -> int:
    parser = argparse.ArgumentParser(prog="nextseek-build-validate")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--project-confirmation")
    parser.add_argument("--out", required=True)
    parser.add_argument("--checks", default="structure,name_check,dag")
    parser.add_argument("--confirm-clear-assays", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        rows = _load_rows(args.rows)
        _preflight_non_empty(rows)
        if args.project_id is None:
            raise GateError("project_id")
        _read_confirmation(args.project_confirmation, args.project_id)
        client = _client(transport)
        schema = _schema_for_rows(client, rows)
        title_map, project_ids, id_to_title = _assay_maps(client, args.project_id)
        resolved_rows = _resolve_additions(rows, client, title_map, project_ids)
        manifest = _resolve_manifest(resolved_rows, client, title_map, project_ids)
        with tempfile.TemporaryDirectory(prefix="nextseek-batch-") as tmp:
            staging = pathlib.Path(tmp)
            _write_manifest(staging / "assay_manifest.json", manifest)
            built = build_payload(
                resolved_rows,
                staging,
                resolved_current=_verified_current(manifest),
                id_to_title=id_to_title,
                sample_type_attributes=schema,
            )
            artifact = pathlib.Path(built[0])
            validation = client.validate_file(artifact, project_id=args.project_id, checks=args.checks)
            _artifact_gate(
                artifact=artifact,
                validation=validation,
                manifest=manifest,
                confirm_clear_assays=set(args.confirm_clear_assays),
            )
            promoted = _promote(artifact, pathlib.Path(args.out))
            print(json.dumps({"artifact": str(promoted), "manifest": manifest}, sort_keys=True))
            return 0
    except GateError as exc:
        _emit_gate(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with a marker.
        _emit_gate(GateError("runner_error", type(exc).__name__))
        return 1


def _load_current(path: str | None) -> dict[str, set[int]]:
    if not path:
        return {}
    raw = json.loads(pathlib.Path(path).read_text())
    return {uid: {int(item) for item in ids} for uid, ids in raw.items()}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


_CMDS = {
    "attrs": _cmd_attrs,
    "extract": _cmd_extract,
    "project-resolve": _cmd_project_resolve,
    "assay-resolve": _cmd_assay_resolve,
    "sample-search": _cmd_sample_search,
    "build-payload": _cmd_build_payload,
    "build-validate": _cmd_build_validate,
}


def main(argv: list[str], *, transport=None) -> int:
    subcmd = argv[0] if argv else ""
    handler = _CMDS.get(subcmd)
    if handler is None:
        sys.stderr.write(f"nextseek-error: unknown or missing subcommand: {subcmd!r}\n")
        return 2
    return handler(argv[1:], transport=transport)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
