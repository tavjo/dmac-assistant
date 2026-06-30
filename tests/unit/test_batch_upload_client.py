# tests/unit/test_batch_upload_client.py
import json
import httpx
import pytest

import sys, pathlib
sys.path.insert(0, str(pathlib.Path("build_context/plugins/nextseek/bin")))
import _batch_upload_client as buc


def _client(handler):
    transport = httpx.MockTransport(handler)
    return buc.BatchUploadClient(base_url="http://ns.test", auth=("u", "p"), transport=transport)


def test_validate_posts_to_validate_endpoint_with_checks():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"valid": True, "summary": "No issues",
                                         "errors": [], "checks_run": ["structure", "name_check", "dag"],
                                         "checks_skipped": [], "totals": {"error": None}})
    c = _client(handler)
    out = c.validate(rows=[{"SampleType": "MUS", "json_metadata": "{\"Name\":\"m1\"}"}],
                     project_id=1, update_existing=False, checks="structure,name_check,dag")
    assert seen["url"].endswith("/nextseek_api/batch-upload/validate/")
    assert seen["body"]["project_id"] == 1
    assert seen["body"]["checks"] == "structure,name_check,dag"
    assert seen["auth"].startswith("Basic ")
    assert out["valid"] is True and out["checks_run"] == ["structure", "name_check", "dag"]


def test_sample_type_attributes_reads_retrieve_endpoint():
    # 2C-2: the per-attribute object is the NESTED SampleTypeSampleAttributeResponse
    # (models.py:1308-1317) — `base_type` lives under `sample_attribute_type`, NOT at top level.
    # Step-0 CONFIRMED: data.attributes.sample_attributes is the list location.
    # Real per-attribute shape also includes: id, description, pid, pos, unit, is_title,
    # sample_controlled_vocab_id, linked_sample_type_id — but client passes raw objects through.
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).endswith("/nextseek_api/sample_types/MUS/")
        return httpx.Response(200, json={"data": {"attributes": {
            "sample_attributes": [
                {"title": "Name", "required": True,
                 "sample_attribute_type": {"id": "1", "title": "String", "base_type": "String", "regexp": None}},
                {"title": "Sex", "required": False,
                 "sample_attribute_type": {"id": "2", "title": "String", "base_type": "String", "regexp": None}}]}}})
    c = _client(handler)
    attrs = c.sample_type_attributes("MUS")
    titles = [a["title"] for a in attrs["attributes"]]
    assert titles == ["Name", "Sex"] and attrs["sample_type"] == "MUS"
    assert attrs["attributes"][0]["sample_attribute_type"]["base_type"] == "String"  # nested, not top-level


def test_list_sample_types_reads_index_endpoint():
    # 2B-1: cover list_sample_types() (SKILL.md step 2 `--list` depends on it).
    # Step-0 CONFIRMED: returns {"data": [{"id": ..., "type": "sample_types", "attributes": {"title": ...}}]}
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).endswith("/nextseek_api/sample_types/")
        return httpx.Response(200, json={"data": [{"id": "12", "attributes": {"title": "MUS"}}]})
    c = _client(handler)
    out = c.list_sample_types()
    assert out and out[0]["attributes"]["title"] == "MUS"


def test_read_samples_gets_retrieve_endpoint():
    # 2C-1: read existing samples for the update-merge via GET /samples/{uid}/ (NOT advanced_search,
    # whose request model is extra='forbid' + requires filter_searchText, so {"filter_uids":[...]} 422s).
    # Step-0 CONFIRMED: attribute_map IS at data.attributes.attribute_map in the real retrieve response.
    # (Probed real UID A.ADCD-250312ALT-1-PUB / SEEK id 319625 — attribute_map confirmed present.)
    seen = {}
    def handler(request):
        seen.setdefault("urls", []).append(str(request.url))
        seen["method"] = request.method
        return httpx.Response(200, json={"data": {
            "id": "321", "type": "samples",
            "attributes": {"attribute_map": {"Name": "m1", "Sex": "M"}},  # confirmed by Step-0 probe
            "relationships": {}, "links": {}, "meta": {}}, "jsonapi": {"version": "1.0"}})
    c = _client(handler)
    out = c.read_samples(["MUS-240101BMC-1"])
    assert seen["method"] == "GET"
    assert seen["urls"][0].endswith("/nextseek_api/samples/MUS-240101BMC-1/")
    # the current attribute map (the merge source) — key/nesting confirmed by the Step-0 real-sample probe
    assert out[0]["data"]["attributes"]["attribute_map"]["Name"] == "m1"


def test_client_post_targets_are_an_allowlist():
    # 2D-2: structural guarantee the client cannot perform the forbidden upload. Enumerate every POST
    # target (not just grep the literal 'batch-upload/start') so a dynamically-constructed upload path is
    # also caught. After 2C-1 the ONLY POST the read-only client issues is the validate endpoint.
    import re
    assert not hasattr(buc.BatchUploadClient, "start")
    assert not hasattr(buc.BatchUploadClient, "upload")
    src = pathlib.Path("build_context/plugins/nextseek/bin/_batch_upload_client.py").read_text()
    post_targets = re.findall(r"\._client\.post\(\s*([^\n,]+)", src)
    assert post_targets, "expected the client to issue at least one POST (validate)"
    ALLOWED = ("batch-upload/validate/",)
    for t in post_targets:
        assert any(a in t for a in ALLOWED), f"POST to a non-allowlisted target: {t.strip()}"
    assert "batch-upload/start" not in src and "/start/" not in src


def test_from_env_requires_creds(monkeypatch):
    for k in ("NEXTSEEK_URL", "NEXTSEEK_BASE_URL", "API_USER", "API_PASS"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as ei:
        buc.BatchUploadClient.from_env()
    assert ei.value.code == 2


def test_from_env_returns_client_when_creds_present(monkeypatch):
    # 2B-1: cover the SUCCESS branch of from_env (creds present -> returns a client), alongside the
    # raise test above, so the 95% gate is reachable without deleting from_env's happy path.
    monkeypatch.setenv("NEXTSEEK_URL", "http://ns.test")
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")
    monkeypatch.delenv("NEXTSEEK_BASE_URL", raising=False)
    c = buc.BatchUploadClient.from_env()
    assert isinstance(c, buc.BatchUploadClient)


def test_from_env_uses_base_url_fallback(monkeypatch):
    # Review #1: the contract names BOTH NEXTSEEK_URL and NEXTSEEK_BASE_URL; exercise the
    # `or os.environ.get("NEXTSEEK_BASE_URL")` fallback branch directly (NEXTSEEK_URL absent).
    monkeypatch.delenv("NEXTSEEK_URL", raising=False)
    monkeypatch.setenv("NEXTSEEK_BASE_URL", "http://fallback.ns.test")
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")
    c = buc.BatchUploadClient.from_env()
    assert isinstance(c, buc.BatchUploadClient)
    # the client's base_url reflects the NEXTSEEK_BASE_URL value (httpx normalizes to a URL)
    assert str(c._client.base_url).rstrip("/") == "http://fallback.ns.test"
