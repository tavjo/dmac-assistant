"""Subcommand dispatcher for the NExtSEEK batch-upload read-only shims.

Exposes main(argv) so the shims can `exec python _batch_upload_runner.py <subcmd> …`
and the runner unit test can call it in-process.

Module-level seams (monkeypatched in tests):
    BatchUploadClient  — from _batch_upload_client
    extract_text       — from _batch_upload_extract
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from _batch_upload_client import BatchUploadClient  # seam: monkeypatched in runner tests
from _batch_upload_extract import extract_text       # seam: monkeypatched in runner tests
from _batch_upload_payload import (
    normalize_rows,
    build,
    merge_attributes,
    check_known_attributes,
)


def _apply_pre_passes(
    raw_rows: list[dict],
    merge_path: str | None,
    known_path: str | None,
) -> list[dict] | None:
    """Apply optional --merge-existing and --known-attrs pre-passes.

    Order of operations (per Task-5 spec, §2B-3 / §2D-1 / 2B-LOW):
    1. Normalize the RAW rows (pre-merge) and run the never-invent check against
       only the keys the user/CC is CHANGING — NOT the full merged set — so that
       legacy DB attributes carried forward by merge_attributes are exempt.
    2. Apply the merge-existing overlay to raw_rows (full attribute-set survival).
    3. Normalize the merged rows for the build/validate payload.

    Returns None if any user-supplied attribute name is not in the known set
    (caller should return a non-zero exit code); writes violations to stderr.
    Returns normalized rows on success.
    """
    existing_map: dict[str, dict] = {}
    known_by_type: dict[str, list[str]] = {}
    if merge_path:
        existing_map = json.loads(pathlib.Path(merge_path).read_text())
    if known_path:
        known_by_type = json.loads(pathlib.Path(known_path).read_text())

    # Step 1: never-invent check on the PRE-MERGE user keys only
    if known_by_type:
        pre_merge_norm = normalize_rows(raw_rows)
        violations = check_known_attributes(pre_merge_norm, known_by_type)
        if violations:
            for st, key in violations:
                sys.stderr.write(
                    f"nextseek-error: invented attribute {key!r} not in {st} known attrs\n"
                )
            return None  # signal failure; caller returns non-zero exit code

    # Step 2: merge-existing overlay (full attribute-set survival; UID preserved)
    merged: list[dict] = []
    for row in raw_rows:
        uid = (row.get("UID") or "").strip()
        if uid and uid in existing_map:
            row = dict(row)
            row["attributes"] = merge_attributes(existing_map[uid], row["attributes"])
        merged.append(row)

    # Step 3: normalize for the build/validate payload
    return normalize_rows(merged)


def _cmd_attrs(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nextseek-sampletype-attrs")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--type", help="SampleType reference (e.g. MUS)")
    g.add_argument("--list", action="store_true", help="list all sample types")
    args = p.parse_args(argv)
    client = BatchUploadClient.from_env()
    if args.list:
        result = client.list_sample_types()
    else:
        result = client.sample_type_attributes(args.type)
    print(json.dumps(result))
    return 0


def _cmd_sample_read(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nextseek-sample-read")
    p.add_argument("--uid", action="append", required=True, dest="uids",
                   help="UID to fetch (repeatable)")
    p.add_argument("--as-merge-map", action="store_true",
                   help="Transform output to {UID: attribute_map} ready for --merge-existing")
    args = p.parse_args(argv)
    client = BatchUploadClient.from_env()
    result = client.read_samples(args.uids)
    if args.as_merge_map:
        # Fail closed on a count mismatch: if read_samples returned fewer bodies than UIDs
        # requested, a dropped UID would later look like "no existing data" to --merge-existing
        # and could silently WIPE that sample's attributes. Refuse to emit a partial map.
        if len(result) != len(args.uids):
            sys.stderr.write(
                f"nextseek-error: sample-read returned {len(result)} of "
                f"{len(args.uids)} requested samples\n"
            )
            return 1
        merge_map: dict[str, dict] = {}
        for uid, body in zip(args.uids, result):
            try:
                attr_map = body["data"]["attributes"]["attribute_map"]
                if not isinstance(attr_map, dict):
                    attr_map = {}
            except (KeyError, TypeError):
                attr_map = {}
            merge_map[uid] = attr_map
        print(json.dumps(merge_map))
    else:
        print(json.dumps(result))
    return 0


def _cmd_validate(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nextseek-validate-upload")
    p.add_argument("--rows", required=True, help="JSON file of raw rows")
    p.add_argument("--project-id", required=True, type=int)
    p.add_argument("--update-existing", default="false",
                   help="true|false (parsed to bool; default false)")
    p.add_argument("--checks", default="structure,name_check,dag")
    p.add_argument("--merge-existing", help="JSON map UID -> existing attribute map")
    p.add_argument("--known-attrs", help="JSON map SampleType -> list of known attr titles")
    p.add_argument("--out", required=True, help="directory to write validation_result.json")
    args = p.parse_args(argv)

    raw_rows = json.loads(pathlib.Path(args.rows).read_text())

    # Parse --update-existing to a real bool (NOT naive bool("false") which is True)
    update_existing = args.update_existing.lower() == "true"

    normalized = _apply_pre_passes(raw_rows, args.merge_existing, args.known_attrs)
    if normalized is None:
        return 1  # violation already written to stderr by _apply_pre_passes

    client = BatchUploadClient.from_env()
    result = client.validate(
        normalized,
        args.project_id,
        update_existing=update_existing,
        checks=args.checks,
    )

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "validation_result.json"
    result_path.write_text(json.dumps(result, indent=2))

    print(json.dumps(result))
    return 0


def _cmd_build_payload(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nextseek-build-payload")
    p.add_argument("--rows", required=True, help="JSON file of raw rows")
    p.add_argument("--format", help="workbook|flat_xlsx|json (auto-selected if absent)")
    p.add_argument("--merge-existing", help="JSON map UID -> existing attribute map")
    p.add_argument("--known-attrs", help="JSON map SampleType -> list of known attr titles")
    p.add_argument("--out", required=True, help="directory to write payload artifact(s)")
    args = p.parse_args(argv)

    raw_rows = json.loads(pathlib.Path(args.rows).read_text())
    normalized = _apply_pre_passes(raw_rows, args.merge_existing, args.known_attrs)
    if normalized is None:
        return 1  # violation already written to stderr by _apply_pre_passes

    written = build(normalized, args.out, requested_format=args.format)
    for path in written:
        print(path)
    return 0


def _cmd_extract(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nextseek-extract-text")
    p.add_argument("--file", required=True, help="path to file to extract text from")
    args = p.parse_args(argv)
    text = extract_text(args.file)
    print(text)
    return 0


_CMDS = {
    "attrs": _cmd_attrs,
    "sample-read": _cmd_sample_read,
    "validate": _cmd_validate,
    "build-payload": _cmd_build_payload,
    "extract": _cmd_extract,
}


def main(argv: list[str]) -> int:
    """Parse the first element of argv as a subcommand and dispatch.

    Returns an integer exit code. Subcommand handlers may raise SystemExit
    (e.g. from argparse errors or CONFIG_MISSING) — callers should let those
    propagate normally.
    """
    subcmd = argv[0] if argv else ""
    handler = _CMDS.get(subcmd)
    if handler is None:
        sys.stderr.write(f"nextseek-error: unknown or missing subcommand: {subcmd!r}\n")
        return 2
    return handler(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
