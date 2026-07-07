from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tools.e2e import verify_live_fidelity as verifier

UID = "D.IMG-230913ENG-1757-PUB"
ORIG_FIXTURE_DIR = verifier.FIXTURE_DIR


def test_verify_live_fidelity_accepts_valid_transcript(tmp_path):
    path = _write(tmp_path, _valid_transcript())
    result = verifier.verify(path)
    assert result["uid"] == UID
    assert result["auth_set"] == [252, 351]
    assert result["resolved"] == [252, 351]
    assert result["breadth_rows"] >= 3


def test_verify_live_fidelity_rejects_missing_required_call(tmp_path):
    transcript = _valid_transcript()
    transcript["calls"] = [call for call in transcript["calls"] if call["name"] != "assays_map"]
    with pytest.raises(verifier.VerificationError, match="missing raw call: assays_map"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_http_error_response(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "sample_detail")["status_code"] = 500
    with pytest.raises(verifier.VerificationError, match="HTTP 500"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_wrong_host(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "advanced_search_uid")["host"] = "nextseek.mit.edu"
    with pytest.raises(verifier.VerificationError, match="not 'nextseek-dev.mit.edu'"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_fixture_title_drift(tmp_path):
    transcript = _valid_transcript()
    row = _probe_row(_named(transcript, "advanced_search_uid")["response_json"])
    row["assays"] = "PCR - Data Linked"
    with pytest.raises(verifier.VerificationError, match="differ from committed fixture"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_numeric_id_drift(tmp_path):
    transcript = _valid_transcript()
    row = _probe_row(_named(transcript, "advanced_search_uid")["response_json"])
    row["id"] = 123
    with pytest.raises(verifier.VerificationError, match="numeric id drifted"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_collision_title_absent(tmp_path):
    transcript = _valid_transcript()
    assays = _named(transcript, "advanced_search_uid")["response_json"]["rows"]
    assays[:] = [row for row in assays if row["json_metadata"]["UID"] == UID]
    _probe_row(_named(transcript, "advanced_search_uid")["response_json"])["assays"] = "Comet Chip - Data Linked"
    fixture_dir = _fixture_copy(tmp_path)
    fixture = json.loads((fixture_dir / "advanced_search_uid.json").read_text(encoding="utf-8"))
    _probe_row(fixture)["assays"] = "Comet Chip - Data Linked"
    (fixture_dir / "advanced_search_uid.json").write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(verifier, "FIXTURE_DIR", fixture_dir)
        with pytest.raises(verifier.VerificationError, match="collision title absent"):
            verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_probe_truncation(tmp_path):
    transcript = _valid_transcript()
    row = _probe_row(_named(transcript, "advanced_search_uid")["response_json"])
    row["assays"] = "x" * 900
    with pytest.raises(verifier.VerificationError, match="truncation-suspect"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_project_confirmation_mismatch(tmp_path):
    transcript = _valid_transcript()
    transcript["project_confirmation"]["project_id"] = 99
    with pytest.raises(verifier.VerificationError, match="project confirmation"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_wrong_membership_candidate(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "assay_samples_351")["response_json"]["data"]["relationships"]["samples"]["data"] = []
    _named(transcript, "assay_samples_260")["response_json"]["data"]["relationships"]["samples"]["data"] = [
        {"type": "samples", "id": "324503"}
    ]
    rel = _named(transcript, "sample_detail")["response_json"]["data"]["relationships"]["assays"]["data"]
    rel[:] = [{"type": "assays", "id": "252"}, {"type": "assays", "id": "260"}]
    with pytest.raises(verifier.VerificationError, match="wrong candidate"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_breadth_out_of_map_title(tmp_path):
    transcript = _valid_transcript()
    row = _named(transcript, "breadth_advanced_search")["response_json"]["rows"][0]
    row["assays"] = "Definitely Not In Live Map"
    with pytest.raises(verifier.VerificationError, match="could not parse assay titles"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_breadth_too_small(tmp_path):
    transcript = _valid_transcript()
    rows = _named(transcript, "breadth_advanced_search")["response_json"]["rows"]
    rows[:] = rows[:2]
    with pytest.raises(verifier.VerificationError, match="fewer than three"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_breadth_truncation(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "breadth_advanced_search")["response_json"]["rows"][0]["assays"] = "x" * 900
    with pytest.raises(verifier.VerificationError, match="breadth row"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_provenance_auth_set(monkeypatch, tmp_path):
    transcript = _valid_transcript()
    fixture_dir = _fixture_copy(tmp_path)
    data = json.loads((fixture_dir / "advanced_search_uid.provenance.json").read_text(encoding="utf-8"))
    data["probe_sample"]["authoritative_assay_ids"] = [252, 351]
    (fixture_dir / "advanced_search_uid.provenance.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(verifier, "FIXTURE_DIR", fixture_dir)
    with pytest.raises(verifier.VerificationError, match="must not contain authoritative_assay_ids"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_auth_set_from_wrong_source(tmp_path):
    transcript = _valid_transcript()
    transcript["auth_set_source"] = "path2_resolution"
    with pytest.raises(verifier.VerificationError, match="AUTH_SET must be sourced from sample_detail"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_resolver_mismatch(tmp_path):
    transcript = _valid_transcript()
    rel = _named(transcript, "sample_detail")["response_json"]["data"]["relationships"]["assays"]["data"]
    rel[:] = [{"type": "assays", "id": "260"}]
    with pytest.raises(verifier.VerificationError, match="resolved assays"):
        verifier.verify(_write(tmp_path, transcript))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda call: call.update(response_json=[]), "not an object"),
        (lambda call: call["response_json"].update(valid=False), "returned invalid"),
        (lambda call: call["response_json"].update(checks_run=["structure"]), "missed required checks"),
        (lambda call: call["response_json"].update(totals={"processed": 2}), "processed count mismatch"),
        (lambda call: call.update(request_form={"checks": ""}), "multipart form field"),
    ],
)
def test_verify_live_fidelity_rejects_validate_conjuncts(tmp_path, mutation, match):
    transcript = _valid_transcript()
    mutation(_named(transcript, "delivered_workbook_validate"))
    with pytest.raises(verifier.VerificationError, match=match):
        verifier.verify(_write(tmp_path, transcript))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda call: call["response_json"].update(data=[]), "assays map response"),
        (lambda call: call.update(endpoint="/wrong/path"), "not a NExtSEEK API path"),
        (lambda call: call.pop("method"), "call missing method"),
    ],
)
def test_verify_live_fidelity_rejects_call_shape_conjuncts(tmp_path, mutation, match):
    transcript = _valid_transcript()
    mutation(_named(transcript, "assays_map"))
    with pytest.raises(verifier.VerificationError, match=match):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_duplicate_call_name(tmp_path):
    transcript = _valid_transcript()
    transcript["calls"].append(copy.deepcopy(transcript["calls"][0]))
    with pytest.raises(verifier.VerificationError, match="duplicate call name"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_reads_response_text_when_json_field_absent(tmp_path):
    transcript = _valid_transcript()
    call = _named(transcript, "assays_map")
    call["response_text"] = json.dumps(call.pop("response_json"))
    result = verifier.verify(_write(tmp_path, transcript))
    assert result["resolved"] == [252, 351]


def test_verify_live_fidelity_rejects_missing_response_body(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "assays_map").pop("response_json")
    with pytest.raises(verifier.VerificationError, match="response_json/response_text"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_duplicate_probe_rows(tmp_path):
    transcript = _valid_transcript()
    row = copy.deepcopy(_probe_row(_named(transcript, "advanced_search_uid")["response_json"]))
    _named(transcript, "advanced_search_uid")["response_json"]["rows"].append(row)
    with pytest.raises(verifier.VerificationError, match="expected exactly one row"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_accepts_string_json_metadata(tmp_path):
    transcript = _valid_transcript()
    row = _probe_row(_named(transcript, "advanced_search_uid")["response_json"])
    row["json_metadata"] = json.dumps(row["json_metadata"])
    result = verifier.verify(_write(tmp_path, transcript))
    assert result["uid"] == UID


def test_verify_live_fidelity_rejects_title_not_in_project(tmp_path):
    transcript = _valid_transcript()
    rel = _named(transcript, "project_assays")["response_json"]["data"]["relationships"]["assays"]["data"]
    rel[:] = [{"type": "assays", "id": "999"}]
    with pytest.raises(verifier.VerificationError, match="not in project"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_path2_no_match(tmp_path):
    transcript = _valid_transcript()
    _named(transcript, "assay_samples_351")["response_json"]["data"]["relationships"]["samples"]["data"] = []
    with pytest.raises(verifier.VerificationError, match="Path-2 failed"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_rejects_bad_title_delimiter(tmp_path):
    transcript = _valid_transcript()
    row = _probe_row(_named(transcript, "advanced_search_uid")["response_json"])
    row["assays"] = row["assays"].replace(",", "")
    with pytest.raises(verifier.VerificationError, match="could not parse assay titles"):
        verifier.verify(_write(tmp_path, transcript))


def test_verify_live_fidelity_main_reports_nonzero_on_failure(tmp_path, capsys):
    transcript = _valid_transcript()
    _named(transcript, "sample_detail")["status_code"] = 500
    assert verifier.main([str(_write(tmp_path, transcript))]) == 1
    assert '"ok": false' in capsys.readouterr().out


def test_verify_live_fidelity_main_reports_success(tmp_path, capsys):
    assert verifier.main([str(_write(tmp_path, _valid_transcript()))]) == 0
    assert '"ok": true' in capsys.readouterr().out


def _valid_transcript() -> dict:
    advanced = _fixture("advanced_search_uid.json")
    assays_map = _fixture("assays_map.json")
    project = _fixture("project_assays.json")
    assay_351 = _fixture("assay_samples_351.json")
    assay_260 = _fixture("assay_samples_260.json")
    return {
        "capture_date": "20260707T000000Z",
        "auth_set_source": "sample_detail",
        "project_confirmation": {
            "project_id": 1,
            "accessible_project_ids": [1],
            "confirmed": True,
        },
        "delivered_workbook": {"row_count": 1, "artifact_name": "payload_flat.xlsx", "project_id": 1},
        "calls": [
            _call("advanced_search_uid", "POST", "/nextseek_api/samples/advanced_search/", advanced),
            _call("sample_detail", "GET", f"/nextseek_api/samples/{UID}/", _sample_detail()),
            _call("assays_map", "GET", "/nextseek_api/assays/", assays_map),
            _call("project_assays", "GET", "/nextseek_api/projects/1/", project),
            _call("assay_samples_260", "GET", "/nextseek_api/assays/260/", assay_260),
            _call("assay_samples_351", "GET", "/nextseek_api/assays/351/", assay_351),
            _call("breadth_advanced_search", "POST", "/nextseek_api/samples/advanced_search/", advanced),
            _call(
                "delivered_workbook_validate",
                "POST",
                "/nextseek_api/batch-upload/validate/",
                {
                    "valid": True,
                    "checks_run": ["structure", "name_check", "dag"],
                    "totals": {"processed": 1},
                },
                request_form={"checks": "structure,name_check,dag", "project_id": "1"},
            ),
        ],
    }


def _sample_detail() -> dict:
    return {
        "data": {
            "id": "324503",
            "type": "samples",
            "relationships": {
                "assays": {
                    "data": [
                        {"type": "assays", "id": "252"},
                        {"type": "assays", "id": "351"},
                    ]
                }
            },
        }
    }


def _call(
    name: str,
    method: str,
    endpoint: str,
    response_json: dict,
    *,
    request_form: dict | None = None,
) -> dict:
    return {
        "name": name,
        "method": method,
        "endpoint": endpoint,
        "host": verifier.DEV_HOST,
        "status_code": 200,
        "response_json": copy.deepcopy(response_json),
        "request_form": request_form,
    }


def _probe_row(advanced: dict) -> dict:
    return next(row for row in advanced["rows"] if row["json_metadata"]["UID"] == UID)


def _named(transcript: dict, name: str) -> dict:
    return next(call for call in transcript["calls"] if call["name"] == name)


def _fixture(name: str) -> dict:
    return json.loads((verifier.FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _fixture_copy(tmp_path: pathlib.Path) -> pathlib.Path:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir(exist_ok=True)
    for source in ORIG_FIXTURE_DIR.glob("*.json"):
        (fixture_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return fixture_dir


def _write(tmp_path: pathlib.Path, transcript: dict) -> pathlib.Path:
    path = tmp_path / "live_fidelity_probe.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")
    return path
