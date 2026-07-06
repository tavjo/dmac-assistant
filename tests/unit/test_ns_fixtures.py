from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from tests.unit.fixtures.ns.duplicate_title_anchor import (
    COLLISION_IDS,
    COLLISION_TITLE,
    PROBE_NUMERIC_SEEK_ID,
)

FIXED_UID = "D.IMG-230913ENG-1757-PUB"
PARENT_SEARCH_TERM = "CEL-230912ENG-2-PUB"
DOC_FIXTURES = Path("docs/research/fixtures/ns")
UNIT_FIXTURES = Path("tests/unit/fixtures/ns")
TARGET_UIDS = {FIXED_UID}
SEARCH_TERMS = {FIXED_UID, PARENT_SEARCH_TERM}


def _load(path: Path):
    return json.loads(path.read_text())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tis_anchor_is_tracked_and_shape_locked():
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(DOC_FIXTURES / "sample_type_TIS.json")],
        check=True,
        stdout=subprocess.PIPE,
    )
    assert _sha(UNIT_FIXTURES / "sample_type_TIS.json") == _sha(DOC_FIXTURES / "sample_type_TIS.json")
    body = _load(UNIT_FIXTURES / "sample_type_TIS.json")
    attrs = body["data"]["attributes"]["sample_attributes"]
    assert len(attrs) == 90
    by_title = {item["title"]: item for item in attrs}
    assert by_title["Name"]["required"] is True
    assert by_title["Scientist"]["required"] is True
    assert [item["title"] for item in attrs if item.get("is_title")] == ["UID"]
    assert by_title["Parent"]["required"] is False
    assert attrs[5]["title"] == "Parent"


def test_advanced_search_anchor_provenance_and_shape():
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(DOC_FIXTURES / "advanced_search_uid.json")],
        check=True,
        stdout=subprocess.PIPE,
    )
    assert _sha(UNIT_FIXTURES / "advanced_search_uid.json") == _sha(DOC_FIXTURES / "advanced_search_uid.json")
    provenance = _load(DOC_FIXTURES / "advanced_search_uid.provenance.json")
    assert provenance["endpoint"] == "/nextseek_api/samples/advanced_search/"
    assert provenance["host"] == "https://nextseek-dev.mit.edu"
    assert provenance["requested_uids"] == [FIXED_UID, PARENT_SEARCH_TERM]
    assert provenance["capture_date"].endswith("Z")
    assert provenance["live_probed"] is True
    assert provenance["sha256"] == _sha(DOC_FIXTURES / "advanced_search_uid.json")
    body = _load(UNIT_FIXTURES / "advanced_search_uid.json")
    assert set(body) >= {"total", "rows"}
    rows = body["rows"]
    assert body["total"] == len(rows)
    target_true_rows = [row for row in rows if row["json_metadata"]["UID"] in TARGET_UIDS]
    false_rows = [
        row
        for row in rows
        if row["json_metadata"].get("UID") not in SEARCH_TERMS
        and row["json_metadata"].get("Parent") in SEARCH_TERMS
    ]
    assert len(target_true_rows) == 1
    assert any(row["json_metadata"]["UID"] == PARENT_SEARCH_TERM for row in rows)
    assert false_rows
    assert all(item["synthesized"] is False for item in provenance["rows"])
    assert provenance["rows"] == [
        {
            "uid": row["json_metadata"]["UID"],
            "role": "true_positive" if row["json_metadata"]["UID"] in SEARCH_TERMS else "false_positive",
            "synthesized": False,
        }
        for row in rows
    ]
    probe = target_true_rows[0]
    assert probe["id"] == PROBE_NUMERIC_SEEK_ID
    assert COLLISION_TITLE in probe["assays"]
    assays_title_set = {
        item["attributes"]["title"]
        for item in _load(UNIT_FIXTURES / "assays_map.json")["data"]
    }
    for row in rows:
        raw_assays = row.get("assays") or ""
        assert isinstance(raw_assays, str)
        for title in [part.strip() for part in raw_assays.split(",") if part.strip()]:
            assert title in assays_title_set
    assert provenance["probe_sample"]["breadth_probe_uids"] == sorted(
        {row["json_metadata"]["UID"] for row in rows},
        key=lambda uid: (
            -next(
                len(str(row.get("assays") or "").split(","))
                for row in rows
                if row["json_metadata"]["UID"] == uid
            ),
            uid,
        ),
    )[:10]


def test_resolution_fixtures_are_cross_consistent():
    for name in [
        "advanced_search_uid.json",
        "advanced_search_uid.provenance.json",
        "assays_map.json",
        "project_assays.json",
        "assay_samples_351.json",
        "assay_samples_260.json",
    ]:
        assert _sha(UNIT_FIXTURES / name) == _sha(DOC_FIXTURES / name)

    assays = _load(UNIT_FIXTURES / "assays_map.json")
    title_map: dict[str, set[int]] = {}
    for item in assays["data"]:
        title_map.setdefault(item["attributes"]["title"], set()).add(int(item["id"]))
        assert "projects" not in item.get("relationships", {})
    assert title_map[COLLISION_TITLE] == COLLISION_IDS

    project = _load(UNIT_FIXTURES / "project_assays.json")
    project_ids = {
        int(item["id"])
        for item in project["data"]["relationships"]["assays"]["data"]
    }
    assert COLLISION_IDS <= project_ids

    samples_351 = {
        int(item["id"])
        for item in _load(UNIT_FIXTURES / "assay_samples_351.json")["data"]["relationships"]["samples"]["data"]
    }
    samples_260 = {
        int(item["id"])
        for item in _load(UNIT_FIXTURES / "assay_samples_260.json")["data"]["relationships"]["samples"]["data"]
    }
    assert PROBE_NUMERIC_SEEK_ID in samples_351
    assert PROBE_NUMERIC_SEEK_ID not in samples_260


def test_duplicate_title_anchor_constants_match_fixtures():
    provenance = _load(DOC_FIXTURES / "advanced_search_uid.provenance.json")
    probe = provenance["probe_sample"]
    assert probe["collision_title"] == COLLISION_TITLE
    assert set(probe["collision_ids"]) == COLLISION_IDS
    assert probe["numeric_seek_id"] == PROBE_NUMERIC_SEEK_ID
    assert probe["membership_assay_id"] == 351
