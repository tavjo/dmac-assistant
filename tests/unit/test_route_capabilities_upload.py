"""
Task 6: Route `upload_payload` requests to `container_cc`.

Tests assert:
  1. container_cc advertises an upload_payload task family with non-empty example_queries.
  2. The registry is still valid JSON with exactly the two routes {nextseek_query, container_cc}.
  3. nextseek_query's not_for now explicitly disclaims payload-building (the $0 deterministic
     anti-misroute lever from hardening 2B-1).
"""

import json
import pathlib


def test_container_cc_has_upload_payload_family():
    data = json.loads(pathlib.Path("build_context/route_capabilities.json").read_text())
    cc = next(r for r in data["routes"] if r["route_name"] == "container_cc")
    fams = {f["name"] for f in cc["task_families"]}
    assert "upload_payload" in fams, "container_cc must advertise upload_payload"
    fam = next(f for f in cc["task_families"] if f["name"] == "upload_payload")
    assert fam["example_queries"], "upload_payload needs example queries"


def test_registry_still_valid_json_and_two_routes():
    data = json.loads(pathlib.Path("build_context/route_capabilities.json").read_text())
    assert {r["route_name"] for r in data["routes"]} == {"nextseek_query", "container_cc"}


def test_nextseek_query_not_for_excludes_payload_building():
    # 2B-1 ($0 deterministic lever): the read-only nextseek_query route must EXPLICITLY disclaim
    # payload-building in its `not_for` (the schema's negative-signal field, verified in
    # build_context/route_capabilities.json) so the LLM router does not misroute
    # "build an upload sheet for these samples" to the read-only pipeline. This is the cheap
    # deterministic complement to the paid live-E2E route proof (Tasks 9-10).
    data = json.loads(pathlib.Path("build_context/route_capabilities.json").read_text())
    nq = next(r for r in data["routes"] if r["route_name"] == "nextseek_query")
    nf = nq["not_for"].lower()
    assert "payload" in nf, "nextseek_query.not_for must disclaim payload-building"
    assert "upload" in nf or "update" in nf
    assert "build" in nf or "prepar" in nf or "validat" in nf
