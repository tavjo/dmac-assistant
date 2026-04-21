"""Pydantic model for the NExtSEEK `nextseek-api` plugin's list/count response.

The canonical DRF shape (per SKILL.md line 371) is:

    {"count": 1247, "next": "https://.../assays/?page[number]=2", "results": [...]}

SKILL.md Example 3 (line 322) shows the bulk-retrieve variant:

    {"results": [...], "total": 3}

Some endpoints return ``records`` instead of ``results`` too, and
count/total-only endpoints omit the items entirely. This module is
intentionally lenient about which of those shapes is present but strict
about the inner item shape (every item must at minimum have a ``uid``)
and about rejecting non-dict payloads.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


_IDENTIFIER_KEYS = ("uid", "uuid", "id")


def _list_has_identifier_dicts(value: Any) -> bool:
    """True iff ``value`` is a non-empty list of dicts each carrying an
    identifier-like key (``uid``/``uuid``/``id``). Used as the final fallback
    in :meth:`ListResponse.has_any_record` so live NExtSEEK responses with
    non-canonical envelopes (``data``/``samples``/etc.) still satisfy the
    DD-18 "got at least one record back" intent.
    """
    if not isinstance(value, list) or not value:
        return False
    if not all(isinstance(v, dict) for v in value):
        return False
    return all(any(k in v for k in _IDENTIFIER_KEYS) for v in value)


class SampleSummary(BaseModel):
    """Minimum-viable sample record. Extra fields are tolerated."""

    model_config = ConfigDict(extra="allow")

    uid: str
    title: str | None = None
    sample_type: str | None = None
    project_id: str | None = None


class ListResponse(BaseModel):
    """DRF-style paginated list envelope with graceful fallbacks.

    Accepts either ``results`` or ``records`` as the item array (stored
    under :attr:`records`), and either ``count`` or ``total`` as the
    cardinality hint (stored under both :attr:`count` and :attr:`total`
    so callers that consult either name see the same number).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    count: int | None = None
    total: int | None = None  # SKILL.md Example 3 alias (bulk-retrieve)
    next: str | None = None
    records: list[SampleSummary] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coalesce_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data  # let the field validators fail with a clear message.
        data = dict(data)
        # Items: precedence is `records` > `results` > `rows` (the last is
        # what live NExtSEEK list endpoints actually return; the SKILL.md
        # examples document the first two).
        if "records" in data:
            data.pop("results", None)
            data.pop("rows", None)
        elif "results" in data:
            data["records"] = data.pop("results")
            data.pop("rows", None)
        elif "rows" in data:
            data["records"] = data.pop("rows")
        # Cardinality: ``total_samples`` is the live NExtSEEK summary-endpoint
        # name; precedence is explicit `count` > `total` > `total_samples`.
        # Cross-populate so downstream code can read whichever name.
        if "count" not in data and "total" in data:
            data["count"] = data["total"]
        if "count" not in data and "total_samples" in data:
            data["count"] = data["total_samples"]
        if "total" not in data and "count" in data:
            data["total"] = data["count"]
        return data

    def has_any_record(self) -> bool:
        """True iff the response proves the dev instance has ≥1 sample.

        DD-18 assertion: "≥1 record OR ≥1 count". Live NExtSEEK endpoints
        use varied envelope shapes — the canonical DRF (``results``), the
        legacy LIH list (``rows``), the JSON:API spec (``data: [...]``),
        and summary endpoints (``data: [{sample_type, n_samples,
        samples:[...]}]``). Beyond the ``records``/``count``/``total`` paths
        already coalesced above, walk the model's extras for any non-empty
        list of identifier-bearing dicts as a final fallback.
        """
        if self.records:
            return True
        n = self.count if self.count is not None else self.total
        if n is not None and n >= 1:
            return True
        for value in (self.model_extra or {}).values():
            if _list_has_identifier_dicts(value):
                return True
        return False


def parse_list_response(payload: str | dict | bytes) -> ListResponse:
    """Parse a raw JSON string/bytes or a dict into a :class:`ListResponse`.

    Raises :class:`ValueError` for null, non-JSON, or non-dict inputs.
    """
    if isinstance(payload, (str, bytes)):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"payload is not valid JSON: {exc.msg}") from exc
    else:
        parsed = payload

    if parsed is None:
        raise ValueError("payload is JSON null")
    if not isinstance(parsed, dict):
        raise ValueError(f"payload must be a JSON object; got {type(parsed).__name__}")

    return ListResponse.model_validate(parsed)
