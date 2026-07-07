"""T9.5 read-only live-fidelity probe for the NExtSEEK batch-upload gate.

This script touches the live dev server only after explicit owner approval. It
loads credentials from a dotenv file and persists raw response/status metadata;
it never prints credential values.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from tools.e2e.verify_live_fidelity import DEV_HOST, REPO_ROOT

BIN_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
FIXTURE_DIR = REPO_ROOT / "docs" / "research" / "fixtures" / "ns"


class Recorder:
    def __init__(self, base_url: str, auth: tuple[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, auth=auth, timeout=60)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        name: str,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.client.request(method, endpoint, params=params, json=json_body)
        self.calls.append(_record_call(name, response, request_json=json_body))
        response.raise_for_status()
        return response.json()


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.recorder.client.send(request)
        name = _name_for_request(request)
        self.recorder.calls.append(
            _record_call(
                name,
                response,
                request_form=_request_form_hint(request),
            )
        )
        return response


def probe(env_file: pathlib.Path, evidence_root: pathlib.Path) -> pathlib.Path:
    load_dotenv(env_file, override=False)
    base = _required_env("NEXTSEEK_URL").rstrip("/")
    user = _required_env("NEXTSEEK_USERNAME")
    password = _required_env("NEXTSEEK_PASSWORD")
    host = urlparse(base).hostname or ""
    if host != DEV_HOST:
        raise SystemExit(f"refusing live-fidelity probe against non-dev host: {host!r}")

    provenance = _load_json(FIXTURE_DIR / "advanced_search_uid.provenance.json")
    probe_sample = provenance["probe_sample"]
    uid = str(probe_sample["uid"])
    collision_ids = [int(item) for item in probe_sample["collision_ids"]]
    project_id = int(probe_sample["confirmed_project_id"])
    breadth_uids = [str(item) for item in probe_sample["breadth_probe_uids"]]

    recorder = Recorder(f"{base}/nextseek_api", (user, password))
    recorder.request(
        "advanced_search_uid",
        "POST",
        "/samples/advanced_search/",
        params={"page_size": 1000},
        json_body={
            "filter_searchText": [uid],
            "searchText_logic": "OR",
            "filter_matchType": "EXACT",
        },
    )
    recorder.request("sample_detail", "GET", f"/samples/{uid}/")
    recorder.request("assays_map", "GET", "/assays/", params={"page_size": 1000})
    recorder.request("project_assays", "GET", f"/projects/{project_id}/")
    for assay_id in sorted(collision_ids):
        recorder.request(f"assay_samples_{assay_id}", "GET", f"/assays/{assay_id}/")
    recorder.request(
        "breadth_advanced_search",
        "POST",
        "/samples/advanced_search/",
        params={"page_size": 1000},
        json_body={
            "filter_searchText": breadth_uids,
            "searchText_logic": "OR",
            "filter_matchType": "EXACT",
        },
    )

    project_confirmation = _project_confirmation(recorder, project_id)
    delivered = _build_and_validate(recorder, project_id, project_confirmation)

    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = evidence_root / now
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = {
        "capture_date": now,
        "auth_set_source": "sample_detail",
        "project_confirmation": project_confirmation,
        "delivered_workbook": delivered,
        "calls": recorder.calls,
    }
    path = out_dir / "live_fidelity_probe.json"
    path.write_text(json.dumps(transcript, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    return path


def _project_confirmation(recorder: Recorder, project_id: int) -> dict[str, Any]:
    projects = recorder.request("project_list", "GET", "/projects/", params={"page_size": 1000})
    accessible = [int(item["id"]) for item in projects.get("data", [])]
    token = {
        "project_id": project_id,
        "accessible_project_ids": accessible,
        "confirmed": project_id in accessible,
    }
    if not token["confirmed"]:
        raise RuntimeError("configured project is not accessible to the live credentials")
    return token


def _build_and_validate(
    recorder: Recorder,
    project_id: int,
    project_confirmation: dict[str, Any],
) -> dict[str, Any]:
    if str(BIN_DIR) not in sys.path:
        sys.path.insert(0, str(BIN_DIR))
    import _batch_upload_runner

    with tempfile.TemporaryDirectory(prefix="nextseek-live-fidelity-") as tmp:
        root = pathlib.Path(tmp)
        rows = root / "rows.json"
        confirmation = root / "project.json"
        out_dir = root / "out"
        rows.write_text(
            json.dumps(
                [
                    {
                        "UID": "",
                        "SampleType": "TIS",
                        "attributes": {"Name": "sample", "Scientist": "Curator", "Parent": "P1"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        confirmation.write_text(json.dumps(project_confirmation), encoding="utf-8")
        old_env = os.environ.copy()
        os.environ["NEXTSEEK_URL"] = recorder.base_url.removesuffix("/nextseek_api")
        try:
            rc = _batch_upload_runner.main(
                [
                    "build-validate",
                    "--rows",
                    str(rows),
                    "--project-id",
                    str(project_id),
                    "--project-confirmation",
                    str(confirmation),
                    "--out",
                    str(out_dir),
                    "--checks",
                    "structure,name_check,dag",
                ],
                transport=RecordingTransport(recorder),
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        if rc != 0:
            raise RuntimeError("shipped build-validate path failed during live-fidelity probe")
        artifact = out_dir / "payload_flat.xlsx"
        return {"row_count": 1, "artifact_name": artifact.name, "project_id": project_id}


def _name_for_request(request: httpx.Request) -> str:
    path = request.url.path
    method = request.method.upper()
    if method == "POST" and path.endswith("/batch-upload/validate/"):
        return "delivered_workbook_validate"
    return f"runner_{method.lower()}_{path.strip('/').replace('/', '_')}"


def _request_form_hint(request: httpx.Request) -> dict[str, str] | None:
    if not request.url.path.endswith("/batch-upload/validate/"):
        return None
    body = request.read().decode("utf-8", errors="replace")
    return {
        "checks": "structure,name_check,dag" if "structure,name_check,dag" in body else "",
        "project_id": _extract_form_value(body, "project_id"),
    }


def _extract_form_value(body: str, name: str) -> str:
    marker = f'name="{name}"'
    idx = body.find(marker)
    if idx < 0:
        return ""
    tail = body[idx + len(marker) :]
    sep = "\r\n\r\n"
    start = tail.find(sep)
    if start < 0:
        return ""
    value = tail[start + len(sep) :]
    return value.split("\r\n", 1)[0]


def _record_call(
    name: str,
    response: httpx.Response,
    *,
    request_json: dict[str, Any] | None = None,
    request_form: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = response.request
    return {
        "name": name,
        "method": request.method,
        "endpoint": request.url.path,
        "host": request.url.host,
        "url": str(request.url),
        "status_code": response.status_code,
        "request_json": request_json,
        "request_form": request_form,
        "response_text": response.text,
        "response_json": _maybe_json(response),
    }


def _maybe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing {name} in dotenv/process environment")
    return value


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--evidence-root", default="evidence/batch-upload-e2e")
    args = parser.parse_args(argv)
    probe(pathlib.Path(args.env_file), pathlib.Path(args.evidence_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
