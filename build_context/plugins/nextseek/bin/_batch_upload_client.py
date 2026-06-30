"""Read-only NExtSEEK batch-upload client. Fetches sample-type attributes, reads
existing samples, and calls the read-only `validate` endpoint. There is deliberately
no upload/update method; the only write-side endpoint is never referenced here, so the
client cannot submit a batch upload.
Auth = per-session user NS login as HTTP Basic (mirrors _assistant_client.py)."""
from __future__ import annotations

import os
import sys
import httpx

_API = "/nextseek_api"


class BatchUploadClient:
    def __init__(self, base_url: str, auth: tuple[str, str],
                 transport: httpx.BaseTransport | None = None, timeout: float = 60.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=auth,
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_env(cls) -> "BatchUploadClient":
        base = os.environ.get("NEXTSEEK_URL") or os.environ.get("NEXTSEEK_BASE_URL") or ""
        user = os.environ.get("API_USER", "")
        pw = os.environ.get("API_PASS", "")
        if not base or not user or not pw:
            sys.stderr.write(
                "nextseek-error: CONFIG_MISSING — NEXTSEEK_URL / API_USER / API_PASS not set\n"
            )
            raise SystemExit(2)
        return cls(base_url=base, auth=(user, pw))

    def list_sample_types(self) -> list[dict]:
        """GET /nextseek_api/sample_types/ — returns the raw data list."""
        r = self._client.get(f"{_API}/sample_types/")
        r.raise_for_status()
        body = r.json()
        return body.get("data", body) if isinstance(body, dict) else body

    def sample_type_attributes(self, type_ref: str) -> dict:
        """GET /nextseek_api/sample_types/{type_ref}/ — returns
        {"sample_type": <ref>, "attributes": [<raw per-attribute object>, ...]}.

        Step-0 confirmed shape: data.attributes.sample_attributes is the list.
        Each per-attribute object: title, required, pos, unit, is_title, and
        sample_attribute_type.base_type (nested, NOT a top-level key).
        """
        r = self._client.get(f"{_API}/sample_types/{type_ref}/")
        r.raise_for_status()
        body = r.json()
        data = body.get("data", {})
        attrs = data.get("attributes", {})
        sample_attrs = attrs.get("sample_attributes", []) if isinstance(attrs, dict) else []
        return {"sample_type": type_ref, "attributes": list(sample_attrs)}

    def read_samples(self, uids: list[str]) -> list[dict]:
        """Per-UID GET /nextseek_api/samples/{uid}/ — returns raw JSON:API bodies.

        2C-1: Step-0 CONFIRMED that data.attributes.attribute_map carries the existing
        attribute name->value map (it IS present on retrieve responses, same key as the
        write-side SamplePatchAttributes, verified against real sample A.ADCD-250312ALT-1-PUB).
        Uses individual GETs rather than the write-endpoint because SampleAdvancedSearchRequest
        is extra='forbid' + requires filter_searchText, so a {"filter_uids": [...]} body 422s.
        """
        out: list[dict] = []
        for uid in uids:
            r = self._client.get(f"{_API}/samples/{uid}/")
            r.raise_for_status()
            out.append(r.json())
        return out

    def validate(self, rows: list[dict], project_id: int, *,
                 update_existing: bool, checks: str) -> dict:
        """POST /nextseek_api/batch-upload/validate/ — returns the ValidationResult dict.

        This is the only POST the client issues. The write/submit endpoint is intentionally
        absent from this class.
        """
        r = self._client.post(
            f"{_API}/batch-upload/validate/",
            json={
                "rows": rows,
                "project_id": project_id,
                "update_existing": update_existing,
                "checks": checks,
            },
        )
        r.raise_for_status()
        return r.json()
