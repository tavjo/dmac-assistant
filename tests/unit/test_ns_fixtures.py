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

DOC_FIXTURES = Path("docs/research/fixtures/ns")
UNIT_FIXTURES = Path("tests/unit/fixtures/ns")
REQUESTED_UIDS = {"D.IMG-230913ENG-1757-PUB", "CEL-230912ENG-2-PUB"}


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
    assert provenance["live_probed"] is True
    assert provenance["sha256"] == _sha(DOC_FIXTURES / "advanced_search_uid.json")
    body = _load(UNIT_FIXTURES / "advanced_search_uid.json")
    rows = body["rows"]
    true_rows = [row for row in rows if row["json_metadata"]["UID"] in REQUESTED_UIDS]
    false_rows = [
        row
        for row in rows
        if row["json_metadata"].get("UID") not in REQUESTED_UIDS
        and row["json_metadata"].get("Parent") in REQUESTED_UIDS
    ]
    assert any(row["json_metadata"]["UID"] == "D.IMG-230913ENG-1757-PUB" for row in true_rows)
    assert false_rows
    probe = next(row for row in rows if row["json_metadata"]["UID"] == "D.IMG-230913ENG-1757-PUB")
    assert probe["id"] == PROBE_NUMERIC_SEEK_ID
    assert COLLISION_TITLE in probe["assays"]


def test_resolution_fixtures_are_cross_consistent():
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
