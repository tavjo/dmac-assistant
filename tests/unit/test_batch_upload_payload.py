import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path("build_context/plugins/nextseek/bin")))
import _batch_upload_payload as bp
import polars as pl
import fastexcel


def test_choose_format_defaults_workbook_for_single_type():
    rows = [{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]
    assert bp.choose_format(rows, None) == "workbook"

def test_choose_format_defaults_flat_xlsx_for_multi_type():
    rows = [{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}},
            {"UID": "", "SampleType": "TIS", "attributes": {"Name": "t1"}}]
    assert bp.choose_format(rows, None) == "flat_xlsx"

def test_choose_format_never_defaults_json():
    rows = [{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]
    assert bp.choose_format(rows, None) != "json"
    assert bp.choose_format(rows, "json") == "json"  # explicit request honored

def test_normalize_blank_uid_is_new_and_absent_in_metadata():
    out = bp.normalize_rows([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}])
    md = json.loads(out[0]["json_metadata"])
    assert out[0]["UID"] in (None, "") and md.get("UID") in (None, "")

def test_normalize_populated_uid_must_match_metadata():
    out = bp.normalize_rows([{"UID": "MUS-240101BMC-1", "SampleType": "MUS",
                              "attributes": {"Name": "m1"}}])
    md = json.loads(out[0]["json_metadata"])
    assert out[0]["UID"] == "MUS-240101BMC-1" == md["UID"]

def test_workbook_multitype_writes_one_file_per_type(tmp_path):
    rows = bp.normalize_rows([
        {"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}},
        {"UID": "", "SampleType": "TIS", "attributes": {"Name": "t1"}},
    ])
    paths = bp.build(rows, str(tmp_path), requested_format="workbook")
    names = sorted(pathlib.Path(p).name for p in paths)
    assert names == ["payload_MUS.xlsx", "payload_TIS.xlsx"]
    # fastexcel lists ALL sheet names (robust even for header-only sheets)
    assert {"Instructions", "Samples", "Ontology", "Assay"} <= set(fastexcel.read_excel(paths[0]).sheet_names)
    samples = pl.read_excel(paths[0], sheet_name="Samples", engine="calamine")
    assert samples.columns[0] == "UID"  # UID column first

def test_flat_xlsx_handles_multitype_in_one_file(tmp_path):
    rows = bp.normalize_rows([
        {"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}},
        {"UID": "", "SampleType": "TIS", "attributes": {"Name": "t1"}},
    ])
    paths = bp.build(rows, str(tmp_path), requested_format="flat_xlsx")
    assert [pathlib.Path(p).name for p in paths] == ["payload_flat.xlsx"]
    df = pl.read_excel(paths[0], engine="calamine")
    assert {"UID", "SampleType", "json_metadata"} <= set(df.columns)


def test_workbook_roundtrip_matches_normalized_rows(tmp_path):
    # 2B-2(a): the artifact that LEAVES the building (the 4-sheet workbook) must carry the SAME data
    # that normalize_rows produced (and that validate checks). Re-read the built workbook and compare
    # its Samples sheet to the normalized json_metadata so an out-of-band/malformed workbook cannot
    # ship while a green verdict was computed on different (flat) data.
    norm = bp.normalize_rows(
        [{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1", "Sex": "M"}}])
    paths = bp.build(norm, str(tmp_path), requested_format="workbook")
    samples = pl.read_excel(paths[0], sheet_name="Samples", engine="calamine")
    rt = {c: samples[c][0] for c in samples.columns}  # single row reconstructed from the workbook
    md = json.loads(norm[0]["json_metadata"])
    assert samples.columns[0] == "UID" and rt["UID"] in ("", None)   # new sample → blank UID
    assert rt["Name"] == "m1" == md["Name"]
    assert rt["Sex"] == "M" == md["Sex"]


def test_merge_attributes_preserves_omitted_keys():
    # 2B-3 / Q-004: on update, attributes present on the existing sample but absent from the user's
    # changes MUST survive (NExtSEEK silently wipes omitted attributes). Deterministic, no network.
    existing = {"Name": "m1", "Sex": "M", "Strain": "C57BL/6"}
    changes = {"Sex": "F"}
    merged = bp.merge_attributes(existing, changes)
    assert merged == {"Name": "m1", "Sex": "F", "Strain": "C57BL/6"}  # full set survives; only Sex changed
    # and the full set flows through normalize_rows for a populated-UID update row
    out = bp.normalize_rows(
        [{"UID": "MUS-240101BMC-1", "SampleType": "MUS", "attributes": {"UID": "MUS-240101BMC-1", **merged}}])
    md = json.loads(out[0]["json_metadata"])
    assert md["Name"] == "m1" and md["Strain"] == "C57BL/6" and md["Sex"] == "F"


def test_check_known_attributes_flags_invented_names():
    # 2D-1: every produced json_metadata key must be a member of the fetched sample-type
    # attribute titles (union {"UID"}); an invented/typo'd name is a violation. Deterministic, no network.
    rows = bp.normalize_rows([
        {"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1", "Sex": "M"}},
        {"UID": "", "SampleType": "MUS", "attributes": {"Wieght": "20g"}},   # invented/typo
    ])
    known = {"MUS": ["Name", "Sex", "Weight"]}
    assert bp.check_known_attributes(rows, known) == [("MUS", "Wieght")]   # only the invented name flagged
    assert bp.check_known_attributes(rows[:1], known) == []                 # all names came from the fetch


def test_check_known_attributes_legacy_key_from_merge_not_rejected():
    # 2B-LOW scoping: merge_attributes carries a legacy DB field (absent from the type's
    # CURRENT definition / `known`) forward on an update (Q-004), but the never-invent check
    # is fed ONLY the user's PRE-MERGE changes, so the legacy key is EXEMPT and does NOT
    # false-reject a legitimate update. Exercises BOTH merge_attributes (carries the legacy
    # key) and check_known_attributes (no violation for it). Deterministic, no network.
    existing = {"Name": "m1", "LegacyDBField": "xyz"}  # legacy, not in `known`
    changes  = {"Sex": "F"}                             # the user's only change
    merged   = bp.merge_attributes(existing, changes)
    assert "LegacyDBField" in merged                    # merge carried it forward (Q-004)
    pre_merge_rows = bp.normalize_rows([
        {"UID": "MUS-1", "SampleType": "MUS",
         "attributes": {"UID": "MUS-1", **changes}}])
    known = {"MUS": ["Name", "Sex", "Weight"]}          # LegacyDBField NOT in known
    # Legacy key is in `merged` but NOT in the pre-merge rows -> no violation:
    assert bp.check_known_attributes(pre_merge_rows, known) == []


def test_build_json_format_writes_payload_rows_json(tmp_path):
    # 2B-1: cover the explicit-json build branch (never the default; only on user request).
    rows = bp.normalize_rows([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}])
    paths = bp.build(rows, str(tmp_path), requested_format="json")
    assert [pathlib.Path(p).name for p in paths] == ["payload_rows.json"]
    loaded = json.loads(pathlib.Path(paths[0]).read_text())
    assert loaded[0]["SampleType"] == "MUS"


def test_normalize_rows_raises_on_uid_mismatch():
    # 2B-1: cover the normalize_rows ValueError branch (UID column != json_metadata.UID).
    import pytest
    with pytest.raises(ValueError):
        bp.normalize_rows([{"UID": "MUS-1", "SampleType": "MUS",
                            "attributes": {"UID": "MUS-2", "Name": "m1"}}])


def test_write_workbook_header_only_when_no_rows(tmp_path):
    # 2B-1: cover the empty-samples_recs (header-only) else-branch of _write_workbook_for_type.
    p = tmp_path / "empty.xlsx"
    bp._write_workbook_for_type([], "MUS", p)
    assert {"Instructions", "Samples", "Ontology", "Assay"} <= set(fastexcel.read_excel(str(p)).sheet_names)
