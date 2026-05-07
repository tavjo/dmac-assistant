"""Auto-pagination helper for NExtSEEK list endpoints (issue #12).

Envelope shape expected from the API:
    {"count": int, "next": str | None, "results": list}

Usage:
    def fetch_page(page_num: int) -> PageEnvelope:
        resp = client.get("assays/", params={"page[number]": page_num})
        return PageEnvelope(
            results=resp["results"],
            next=resp.get("next"),
            total=resp.get("count"),
        )
    items = paginate(fetch_page)

The server-side default page size for NExtSEEK list endpoints is not recorded
in the OpenAPI schema or pyproject config inspected for this task; it is
unknown - probe during Task 09 docs pass.

<!-- PAGINATION: see paginate() in scripts/lib/pagination.py -->
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class PageEnvelope:
    """Normalized pagination envelope.

    Callers construct this from an endpoint-specific response shape; the
    pagination helper stays generic and does not couple to any single schema.
    """

    results: list
    next: str | None = None
    total: int | None = None


DEFAULT_MAX_PAGES = 100


def paginate(
    fetch_page: Callable[[int], PageEnvelope],
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list:
    """Drive ``fetch_page(page_num)`` until no more results.

    Termination conditions (whichever comes first):
      * ``page.results`` is empty
      * ``page.next`` is None
      * ``max_pages`` reached (logs a warning)

    Propagates any exception raised by ``fetch_page`` - no silent swallowing.
    """
    out: list = []
    for page_num in range(1, max_pages + 1):
        page = fetch_page(page_num)
        if not page.results:
            break
        out.extend(page.results)
        if page.next is None:
            break
    else:
        logger.warning(
            "pagination hit max_pages=%d cap before natural end (got %d items)",
            max_pages,
            len(out),
        )
    return out


def probe_default_page_size(fetch_page: Callable[[int], PageEnvelope]) -> int:
    """Issue one page fetch without overriding size; return ``len(results)``.

    Used during Phase 3 Explore / Task 09 docs authoring to document the
    server's default page size for SKILL.md. Not used at runtime.
    """
    page = fetch_page(1)
    return len(page.results)
