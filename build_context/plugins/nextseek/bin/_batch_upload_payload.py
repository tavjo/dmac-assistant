"""Deterministic NExtSEEK batch-upload payload builder. Encodes the UID rule
(blank=new / populated=update; UID column == json_metadata.UID) and the
output-format default rule (single type -> 4-sheet workbook; multi type ->
flat single-sheet xlsx; JSON never the default). No network, no DB.

Contract alignment with NExtSEEK parse_traditional_file (convert.py:202-334):
- One sample type per workbook file (parser rejects >1 type per file).
- INSTRUCTIONS Database Field = "<SampleType>::<attr>" (parser splits on ::).
- SAMPLES headers trim-match INSTRUCTIONS Field values (parser does trim-only normalization).
- json_metadata KEY = the matched Field (same titles in both INSTRUCTIONS and SAMPLES headers).
- UID special-cased: SAMPLES "UID" column sets InputRowModel.UID and mirrors to json_metadata["UID"].
- Empty Ontology/Assay sheets are written header-only; they parse to empty lists (vacuous valid).
"""
from __future__ import annotations

import json
import pathlib

import polars as pl
import xlsxwriter

_SHEETS = ("Instructions", "Samples", "Ontology", "Assay")


def normalize_rows(rows: list[dict]) -> list[dict]:
    """Build NExtSEEK InputRowModel-shaped rows.

    UID rule:
    - blank UID -> new sample: UID is None/absent in json_metadata
    - populated UID -> update: UID must equal attributes["UID"] if that key is set;
      UID is mirrored into json_metadata["UID"]
    Raises ValueError if a populated UID disagrees with attributes["UID"].
    """
    out: list[dict] = []
    for r in rows:
        uid = (r.get("UID") or "").strip()
        attrs = dict(r.get("attributes") or {})
        # Extract the UID already stored in attributes (if any)
        meta_uid = (attrs.get("UID") or "").strip() if attrs.get("UID") is not None else ""
        # Conflict check: both sides populated AND disagree
        if uid and meta_uid and uid != meta_uid:
            raise ValueError(
                f"UID column {uid!r} disagrees with json_metadata.UID {meta_uid!r}"
            )
        # Build metadata: strip the UID key from attrs, then re-apply it per the rule
        md = {k: v for k, v in attrs.items() if k != "UID"}
        if uid:
            md["UID"] = uid
        else:
            md["UID"] = None  # new sample: UID absent/null in metadata
        out.append({
            "UID": uid or None,
            "SampleType": r["SampleType"],
            "json_metadata": json.dumps(md),
            "assay_ids": list(r.get("assay_ids") or []),
        })
    return out


def choose_format(rows: list[dict], requested: str | None) -> str:
    """Return the output format to use.

    If `requested` is one of "workbook"/"flat_xlsx"/"json", return it verbatim.
    Otherwise auto-select:
    - "json" is NEVER auto-chosen.
    - >1 SampleType in rows -> "flat_xlsx"
    - single SampleType -> "workbook"
    """
    if requested in ("workbook", "flat_xlsx", "json"):
        return requested
    types = {r["SampleType"] for r in rows}
    return "flat_xlsx" if len(types) > 1 else "workbook"


def merge_attributes(existing: dict, changes: dict) -> dict:
    """Overlay `changes` onto the existing sample's attribute map and return the FULL set.

    Keys present in `existing` but absent from `changes` SURVIVE — this is the Q-004
    silent-wipe guard: NExtSEEK silently wipes attributes omitted on an update payload,
    so an update payload must carry the FULL attribute set, not just the changed keys.
    Pure function, no I/O.
    """
    merged = dict(existing or {})
    merged.update(changes or {})
    return merged


def check_known_attributes(
    rows: list[dict],
    known_by_type: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Return every (SampleType, key) in normalized rows whose json_metadata key is NOT in
    the fetched attribute titles for that type (union {"UID"}).

    An empty list means no invented attribute names. Enforces the locked
    "never invent attribute names" rule (curation-reference Rule 4.2) deterministically.

    Scoping note: at runtime the caller feeds this function the rows' OWN PRE-MERGE
    attributes (the keys CC/user is CHANGING), not the full merged set. Legacy DB
    attributes carried forward by merge_attributes are exempt; only user/CC-invented
    names are caught. The function itself is unchanged; the scoping is the caller's
    responsibility (Task 5).

    A SampleType missing from `known_by_type` has an empty known set, so its
    attributes are all flagged (no silent bypass). Pure, no I/O.
    """
    violations: list[tuple[str, str]] = []
    for r in rows:
        allowed = set(known_by_type.get(r["SampleType"], [])) | {"UID"}
        for k in json.loads(r["json_metadata"]):
            if k not in allowed:
                violations.append((r["SampleType"], k))
    return violations


# ── Internal workbook helpers ────────────────────────────────────────────────

def _samples_header(rows: list[dict]) -> list[str]:
    """Build the SAMPLES column order: UID first, then all other attribute titles
    in first-seen order across all rows."""
    attr_titles: list[str] = []
    for r in rows:
        for k in json.loads(r["json_metadata"]):
            if k != "UID" and k not in attr_titles:
                attr_titles.append(k)
    return ["UID"] + attr_titles


def _write_workbook_for_type(
    rows: list[dict], sample_type: str, path: pathlib.Path
) -> None:
    """Write a 4-sheet NExtSEEK traditional-format workbook for a single sample type.

    Sheet order: Instructions, Samples, Ontology, Assay (as required by parse_traditional_file).
    Uses a shared xlsxwriter.Workbook so polars writes all four sheets into one file.

    Contract alignment (convert.py:202-334):
    - INSTRUCTIONS: Field=<title>, Database Field=<SampleType>::<title>, Field Type="Text".
    - SAMPLES: headers = same titles as INSTRUCTIONS Field (trim-match guaranteed).
    - UID column is first and special-cased by the parser (sets InputRowModel.UID +
      json_metadata["UID"] regardless of INSTRUCTIONS lookup).
    - Empty Ontology/Assay sheets are written header-only; parse to [] (vacuous valid).
    - include_header=True, table_style=None, autofilter=False -> plain row-1 header cells.
    """
    header = _samples_header(rows)

    # Build SAMPLES records (UID first, then attribute columns, all as strings)
    samples_recs = []
    for r in rows:
        md = json.loads(r["json_metadata"])
        rec: dict = {"UID": r["UID"] or ""}
        for t in header[1:]:
            val = md.get(t)
            rec[t] = "" if val is None else str(val)
        samples_recs.append(rec)

    str_schema = {c: pl.Utf8 for c in header}
    df_samples = (
        pl.DataFrame(samples_recs, schema=str_schema)
        if samples_recs
        else pl.DataFrame(schema=str_schema)
    )

    # INSTRUCTIONS sheet: one row per column, Field = attribute title, Database Field = TYPE::title
    df_instr = pl.DataFrame(
        {
            "Field": header,
            "Database Field": [f"{sample_type}::{t}" for t in header],
            "Field Type": ["Text"] * len(header),
            "Ontology": [""] * len(header),
        },
        schema={
            "Field": pl.Utf8,
            "Database Field": pl.Utf8,
            "Field Type": pl.Utf8,
            "Ontology": pl.Utf8,
        },
    )

    # Empty header-only sheets for Ontology and Assay
    df_ontology = pl.DataFrame(schema={"Ontology": pl.Utf8})
    df_assay = pl.DataFrame(
        schema={
            "SampleType": pl.Utf8,
            "AssayType": pl.Utf8,
            "Assay": pl.Utf8,
            "Direction": pl.Utf8,
        }
    )

    sheet_dfs = {
        "Instructions": df_instr,
        "Samples": df_samples,
        "Ontology": df_ontology,
        "Assay": df_assay,
    }

    # Write all four sheets into a single xlsxwriter Workbook in canonical order.
    # Passing the shared Workbook object to write_excel lets polars add worksheets
    # without closing/reopening the file.
    with xlsxwriter.Workbook(str(path)) as wb:
        for name in _SHEETS:
            sheet_dfs[name].write_excel(
                workbook=wb,
                worksheet=name,
                include_header=True,
                autofilter=False,
                table_style=None,
            )


def _write_flat_xlsx(rows: list[dict], path: pathlib.Path) -> None:
    """Write a single-sheet flat xlsx carrying UID, SampleType, json_metadata, assay_ids."""
    df = pl.DataFrame(
        {
            "UID": [r["UID"] or "" for r in rows],
            "SampleType": [r["SampleType"] for r in rows],
            "json_metadata": [r["json_metadata"] for r in rows],
            "assay_ids": [",".join(str(a) for a in r["assay_ids"]) for r in rows],
        },
        schema={
            "UID": pl.Utf8,
            "SampleType": pl.Utf8,
            "json_metadata": pl.Utf8,
            "assay_ids": pl.Utf8,
        },
    )
    df.write_excel(
        workbook=str(path),
        worksheet="Samples",
        include_header=True,
        autofilter=False,
        table_style=None,
    )


# ── Public build entry point ─────────────────────────────────────────────────

def build(
    rows: list[dict],
    out_dir: str,
    *,
    requested_format: str | None = None,
) -> list[str]:
    """Write payload artifact(s) under `out_dir` and return sorted written paths.

    Format dispatch:
    - "json"      -> payload_rows.json (explicit request only; never the default)
    - "flat_xlsx" -> payload_flat.xlsx (single sheet, all types mixed)
    - "workbook"  -> payload_<SampleType>.xlsx per type (4-sheet NExtSEEK traditional format)
    """
    fmt = choose_format(rows, requested_format)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    if fmt == "json":
        p = out / "payload_rows.json"
        p.write_text(json.dumps(rows, indent=2))
        written.append(str(p))

    elif fmt == "flat_xlsx":
        p = out / "payload_flat.xlsx"
        _write_flat_xlsx(rows, p)
        written.append(str(p))

    else:  # workbook — one file per sample type, sorted for determinism
        by_type: dict[str, list[dict]] = {}
        for r in rows:
            by_type.setdefault(r["SampleType"], []).append(r)
        for st, st_rows in sorted(by_type.items()):
            p = out / f"payload_{st}.xlsx"
            _write_workbook_for_type(st_rows, st, p)
            written.append(str(p))

    return sorted(written)
