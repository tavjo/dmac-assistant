# tests/unit/test_batch_upload_runner.py
import json, sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path("build_context/plugins/nextseek/bin")))
import _batch_upload_runner as runner   # must expose main(argv) -> int and module-level
                                        # BatchUploadClient + extract_text seams (see Step 3)


class _StubClient:
    last = None
    def __init__(self):
        self.calls = []
        type(self).last = self
    @classmethod
    def from_env(cls):
        return cls()
    def sample_type_attributes(self, type_ref):
        self.calls.append(("attrs", type_ref))
        return {"sample_type": type_ref, "attributes": [{"title": "Name", "required": True}]}
    def read_samples(self, uids):
        self.calls.append(("read", list(uids)))
        return [{"data": {"attributes": {"attribute_map": {"Name": "m1"}}}}]
    def validate(self, rows, project_id, *, update_existing, checks):
        self.calls.append(("validate", project_id, checks))
        self.rows_seen = rows                          # LOW(2B): record the rows actually POSTed
        self.update_existing_seen = update_existing   # 2D-F3: record the parsed bool kwarg
        return {"valid": True, "summary": "ok", "errors": [],
                "checks_run": ["structure", "name_check", "dag"], "checks_skipped": []}


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(runner, "BatchUploadClient", _StubClient)
    return _StubClient


def test_runner_attrs_prints_attribute_json(stubbed, capsys):
    assert runner.main(["attrs", "--type", "MUS"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["sample_type"] == "MUS" and data["attributes"][0]["title"] == "Name"
    assert ("attrs", "MUS") in stubbed.last.calls


def test_runner_sample_read_prints_existing_attribute_map(stubbed, capsys):
    assert runner.main(["sample-read", "--uid", "MUS-240101BMC-1"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body[0]["data"]["attributes"]["attribute_map"]["Name"] == "m1"
    assert ("read", ["MUS-240101BMC-1"]) in stubbed.last.calls


def test_runner_validate_writes_result_file_and_prints_verdict(stubbed, capsys, tmp_path):
    rows = tmp_path / "rows.json"   # raw {UID, SampleType, attributes} rows; the runner normalizes them
    rows.write_text(json.dumps([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]))
    out_dir = tmp_path / "out"
    rc = runner.main(["validate", "--rows", str(rows), "--project-id", "1",
                      "--update-existing", "false", "--checks", "structure,name_check,dag",
                      "--out", str(out_dir)])
    assert rc == 0
    written = out_dir / "validation_result.json"
    assert written.is_file(), "validate must persist validation_result.json under --out"
    saved = json.loads(written.read_text())
    assert saved["valid"] is True and "structure" in saved["checks_run"]
    assert "valid" in capsys.readouterr().out.lower()           # verdict echoed to stdout
    assert any(c[0] == "validate" for c in stubbed.last.calls)  # real dispatch, not a no-op


def test_runner_validate_parses_update_existing_bool(stubbed, tmp_path):
    # 2D-F3: pin the --update-existing <true|false> -> real bool parse (a naive bool("false") is True,
    # so an unguarded parse would send update_existing=True for "false"). The stub records the kwarg
    # actually passed to client.validate; assert "false"->False and "true"->True. (Low impact because the
    # server validate ignores update_existing, but the parse must be pinned.)
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]))
    assert runner.main(["validate", "--rows", str(rows), "--project-id", "1",
                        "--update-existing", "false", "--checks", "structure,name_check,dag",
                        "--out", str(tmp_path / "f")]) == 0
    assert stubbed.last.update_existing_seen is False   # "false" must NOT become bool("false")==True
    assert runner.main(["validate", "--rows", str(rows), "--project-id", "1",
                        "--update-existing", "true", "--checks", "structure,name_check,dag",
                        "--out", str(tmp_path / "t")]) == 0
    assert stubbed.last.update_existing_seen is True     # "true" -> True


def test_runner_validate_posts_normalized_rows(stubbed, tmp_path):
    # LOW (pass-6 2B): the runner MUST normalize_rows the RAW --rows BEFORE posting to client.validate. The
    # server's InputRowModel REQUIRES json_metadata (a JSON string); RAW {UID, SampleType, attributes} rows lack
    # it and 422 LIVE. A runner that forwarded the raw rows would pass every other unit assertion and only fail at
    # the PAID live E2E (server 422) — so pin here, for $0, that what is POSTed is the normalize_rows OUTPUT shape
    # ({UID, SampleType, json_metadata, assay_ids}): each posted row has a json_metadata JSON-string key and NO raw
    # `attributes` key.
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]))
    assert runner.main(["validate", "--rows", str(rows), "--project-id", "1",
                        "--update-existing", "false", "--checks", "structure,name_check,dag",
                        "--out", str(tmp_path / "n")]) == 0
    posted = stubbed.last.rows_seen
    assert posted, "validate must POST a non-empty rows list"
    for r in posted:
        assert "attributes" not in r, "validate must NOT post the raw `attributes` key (un-normalized row)"
        assert isinstance(r.get("json_metadata"), str), "validate must post normalized rows (json_metadata string)"
        json.loads(r["json_metadata"])              # the posted json_metadata parses as JSON
        assert r.get("SampleType") == "MUS"


def test_runner_build_payload_writes_artifact(stubbed, capsys, tmp_path):
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "", "SampleType": "MUS", "attributes": {"Name": "m1"}}]))
    out_dir = tmp_path / "out"
    assert runner.main(["build-payload", "--rows", str(rows), "--out", str(out_dir)]) == 0
    assert list(out_dir.glob("payload_*.xlsx")), "build-payload must write a payload artifact"


def test_runner_build_payload_merges_existing_attributes(stubbed, tmp_path):
    # 2B-3 / Q-004: --merge-existing makes the full-attribute-set survival DETERMINISTIC code in the
    # build path (not CC reasoning). The update row changes only Sex; Name/Strain must survive the merge.
    import polars as pl
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "MUS-240101BMC-1", "SampleType": "MUS",
                                 "attributes": {"UID": "MUS-240101BMC-1", "Sex": "F"}}]))
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps({"MUS-240101BMC-1": {"Name": "m1", "Sex": "M", "Strain": "C57BL/6"}}))
    known = tmp_path / "known.json"   # also exercises the --known-attrs no-violation pass-through path
    known.write_text(json.dumps({"MUS": ["Name", "Sex", "Strain"]}))
    out_dir = tmp_path / "out"
    assert runner.main(["build-payload", "--rows", str(rows), "--merge-existing", str(existing),
                        "--known-attrs", str(known), "--out", str(out_dir)]) == 0
    wb = next(iter(out_dir.glob("payload_*.xlsx")))
    samples = pl.read_excel(str(wb), sheet_name="Samples", engine="calamine")
    assert {"UID", "Name", "Sex", "Strain"} <= set(samples.columns)   # omitted Name/Strain survived
    assert samples["Sex"][0] == "F" and samples["Name"][0] == "m1" and samples["Strain"][0] == "C57BL/6"


def test_runner_build_payload_rejects_invented_attribute(stubbed, tmp_path):
    # 2D-1 / never-invent: with --known-attrs supplied, a row whose attribute name is not in the fetched
    # sample-type titles is rejected deterministically (non-zero exit, no artifact written).
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "", "SampleType": "MUS", "attributes": {"Wieght": "20g"}}]))
    known = tmp_path / "known.json"
    known.write_text(json.dumps({"MUS": ["Name", "Sex", "Weight"]}))
    out_dir = tmp_path / "out"
    rc = runner.main(["build-payload", "--rows", str(rows),
                      "--known-attrs", str(known), "--out", str(out_dir)])
    assert rc != 0, "an invented attribute name must be rejected"
    assert not list(out_dir.glob("payload_*.xlsx")), "no artifact when an attribute name is invented"


def test_runner_known_attrs_exempts_merged_legacy_attribute(stubbed, tmp_path):
    # 2B-LOW (pass-7): the never-invent check is scoped to the keys the USER is CHANGING (the row's OWN PRE-MERGE
    # attributes), NOT the full merged set. On an update, --merge-existing carries forward ALL of the real sample's
    # current attributes; a LEGACY attribute no longer in the type's CURRENT definition (so absent from --known-attrs)
    # must NOT false-reject a legitimate update, and must SURVIVE the merge (Q-004 full-set survival).
    import polars as pl
    rows = tmp_path / "rows.json"
    # the user changes ONLY Sex (a known attr); the row supplies no invented name
    rows.write_text(json.dumps([{"UID": "MUS-240101BMC-1", "SampleType": "MUS",
                                 "attributes": {"UID": "MUS-240101BMC-1", "Sex": "F"}}]))
    existing = tmp_path / "existing.json"   # the real sample carries a LEGACY attr not in --known-attrs
    existing.write_text(json.dumps(
        {"MUS-240101BMC-1": {"Name": "m1", "Sex": "M", "LegacyField": "old"}}))
    known = tmp_path / "known.json"          # CURRENT type definition: NO "LegacyField"
    known.write_text(json.dumps({"MUS": ["Name", "Sex"]}))
    out_dir = tmp_path / "out"
    rc = runner.main(["build-payload", "--rows", str(rows), "--merge-existing", str(existing),
                      "--known-attrs", str(known), "--out", str(out_dir)])
    assert rc == 0, "a merged-in legacy DB attribute must NOT trip the never-invent check"
    wb = next(iter(out_dir.glob("payload_*.xlsx")))
    samples = pl.read_excel(str(wb), sheet_name="Samples", engine="calamine")
    assert "LegacyField" in set(samples.columns) and samples["LegacyField"][0] == "old"  # preserved, not rejected
    assert samples["Sex"][0] == "F" and samples["Name"][0] == "m1"


def test_runner_extract_prints_text(stubbed, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "extract_text", lambda p: "Subject: A123")
    f = tmp_path / "protocol.pdf"; f.write_text("x")
    assert runner.main(["extract", "--file", str(f)]) == 0
    assert "Subject: A123" in capsys.readouterr().out


def test_runner_merge_existing_skips_row_uid_not_in_map(stubbed, tmp_path):
    # 2B-3 branch: a NON-BLANK-UID row whose UID is ABSENT from the --merge-existing map must build with
    # ONLY its own attributes (the merge is skipped for that row — not an error). Covers the
    # "uid not in existing_map" branch so 95% is reachable without DI.
    import polars as pl
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([{"UID": "MUS-NOTINMAP-9", "SampleType": "MUS",
                                 "attributes": {"UID": "MUS-NOTINMAP-9", "Sex": "F"}}]))
    existing = tmp_path / "existing.json"   # map covers a DIFFERENT uid -> this row's uid is not present
    existing.write_text(json.dumps({"MUS-240101BMC-1": {"Name": "m1", "Sex": "M", "Strain": "C57BL/6"}}))
    out_dir = tmp_path / "out"
    assert runner.main(["build-payload", "--rows", str(rows), "--merge-existing", str(existing),
                        "--out", str(out_dir)]) == 0
    wb = next(iter(out_dir.glob("payload_*.xlsx")))
    samples = pl.read_excel(str(wb), sheet_name="Samples", engine="calamine")
    assert samples["Sex"][0] == "F"                 # the row's own attribute survives
    assert "Strain" not in set(samples.columns)     # nothing merged in (the uid was not in the map)


def test_runner_sample_read_as_merge_map_single_uid(stubbed, capsys):
    # --as-merge-map flag: one UID, real Step-0 shape {data: {attributes: {attribute_map: {...}}}}
    # Output must be exactly {<UID>: {<title>: <value>}} — no raw JSON:API envelope.
    assert runner.main(["sample-read", "--uid", "MUS-240101BMC-1", "--as-merge-map"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"MUS-240101BMC-1": {"Name": "m1"}}, (
        "--as-merge-map must emit {UID: attribute_map} not the raw JSON:API body"
    )
    assert ("read", ["MUS-240101BMC-1"]) in stubbed.last.calls


def test_runner_sample_read_as_merge_map_two_uids(capsys, monkeypatch):
    # --as-merge-map with two UIDs — stub returns two different attribute_maps.
    class _TwoSampleClient:
        last = None
        def __init__(self): type(self).last = self; self.calls = []
        @classmethod
        def from_env(cls): return cls()
        def read_samples(self, uids):
            self.calls.append(("read", list(uids)))
            return [
                {"data": {"attributes": {"attribute_map": {"Name": "alpha", "Sex": "F"}}}},
                {"data": {"attributes": {"attribute_map": {"Name": "beta",  "Sex": "M"}}}},
            ]

    monkeypatch.setattr(runner, "BatchUploadClient", _TwoSampleClient)
    assert runner.main(["sample-read",
                        "--uid", "MUS-1", "--uid", "MUS-2",
                        "--as-merge-map"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "MUS-1": {"Name": "alpha", "Sex": "F"},
        "MUS-2": {"Name": "beta",  "Sex": "M"},
    }


def test_runner_sample_read_as_merge_map_missing_attribute_map(capsys, monkeypatch):
    # Graceful handling: if a sample's body lacks data.attributes.attribute_map, emit
    # an empty map for that UID rather than crashing.
    class _MissingMapClient:
        @classmethod
        def from_env(cls): return cls()
        def read_samples(self, uids):
            return [{"data": {"attributes": {}}}]   # no attribute_map key

    monkeypatch.setattr(runner, "BatchUploadClient", _MissingMapClient)
    assert runner.main(["sample-read", "--uid", "MUS-999", "--as-merge-map"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"MUS-999": {}}, "missing attribute_map must yield empty dict, not a crash"


def test_runner_sample_read_as_merge_map_fails_closed_on_count_mismatch(capsys, monkeypatch):
    # Silent-wipe guard: if read_samples returns FEWER bodies than UIDs requested, a dropped UID
    # would later look like "no existing data" to --merge-existing and could WIPE that sample's
    # attributes. The flag must FAIL CLOSED (nonzero exit, NO partial map on stdout).
    class _ShortClient:
        @classmethod
        def from_env(cls): return cls()
        def read_samples(self, uids):
            # 2 UIDs requested, only 1 body returned
            return [{"data": {"attributes": {"attribute_map": {"Name": "m1"}}}}]

    monkeypatch.setattr(runner, "BatchUploadClient", _ShortClient)
    rc = runner.main(["sample-read", "--uid", "MUS-1", "--uid", "MUS-2", "--as-merge-map"])
    out = capsys.readouterr()
    assert rc != 0, "count mismatch must fail closed (nonzero exit)"
    assert out.out.strip() == "", "must NOT emit a partial merge map on stdout"
    assert "of" in out.err.lower() and "sample" in out.err.lower()


def test_runner_sample_read_raw_path_unchanged_by_merge_map_flag(stubbed, capsys):
    # WITHOUT --as-merge-map, output must still be the raw JSON:API list (back-compat).
    assert runner.main(["sample-read", "--uid", "MUS-240101BMC-1"]) == 0
    body = json.loads(capsys.readouterr().out)
    # The stub returns [{data: {attributes: {attribute_map: {Name: "m1"}}}}]
    assert isinstance(body, list) and body[0]["data"]["attributes"]["attribute_map"]["Name"] == "m1"


def test_runner_config_missing_propagates(monkeypatch):
    # 2B-3 branch: when BatchUploadClient.from_env raises SystemExit(2) (CONFIG_MISSING — creds/URL absent),
    # a subcommand that constructs the client PROPAGATES a non-zero exit (it does not swallow it or exit 0).
    # Covers the CONFIG_MISSING propagation path so 95% is reachable. Overrides the stub seam directly.
    import pytest
    class _NoCredsClient:
        @classmethod
        def from_env(cls):
            raise SystemExit(2)
    monkeypatch.setattr(runner, "BatchUploadClient", _NoCredsClient)
    with pytest.raises(SystemExit) as ei:
        runner.main(["attrs", "--type", "MUS"])
    assert ei.value.code == 2


def test_runner_unknown_subcommand_errors(stubbed):
    # 2B-1: cover the runner's unknown-subcommand / arg-error branch so the 95% gate is reachable
    # without deleting the dispatcher's error handling. argparse subparsers raise SystemExit(2) on an
    # unknown subcommand; a manual dispatcher returns a non-zero code -> accept either.
    try:
        rc = runner.main(["definitely-not-a-subcommand"])
    except SystemExit as exc:
        assert exc.code not in (0, None)
    else:
        assert rc != 0
