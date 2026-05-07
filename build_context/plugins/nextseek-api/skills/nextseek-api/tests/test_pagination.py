"""Behavioral tests for scripts/lib/pagination.py (task-05-pagination).

Note: spec Section 5 uses `from scripts.lib.pagination import ...`, but the
project's pytest pythonpath is `skills/nextseek-api/scripts` (see pyproject.toml
and tests/conftest.py), so all sibling tests import as `from lib.X`. We follow
the project convention; the module contract (PageEnvelope + paginate) is
unchanged.
"""
from __future__ import annotations

import logging

import pytest

from lib.pagination import PageEnvelope, paginate, probe_default_page_size


def _mk_envelope(items, next_url=None):
    return PageEnvelope(results=items, next=next_url, total=None)


class TestPaginate:
    def test_concatenates_pages(self):
        pages = {
            1: _mk_envelope([{"id": i} for i in range(10)], next_url="?page=2"),
            2: _mk_envelope([{"id": i} for i in range(10, 20)], next_url="?page=3"),
            3: _mk_envelope([{"id": i} for i in range(20, 30)], next_url=None),
        }

        def fetch(n):
            return pages[n]

        result = paginate(fetch)
        assert len(result) == 30
        assert result[0]["id"] == 0
        assert result[-1]["id"] == 29

    def test_stops_on_next_null(self):
        pages = {
            1: _mk_envelope([{"x": 1}], next_url="?page=2"),
            2: _mk_envelope([{"x": 2}], next_url=None),
            3: _mk_envelope([{"x": 3}], next_url="?page=4"),  # unreachable
        }
        calls = []

        def fetch(n):
            calls.append(n)
            return pages[n]

        result = paginate(fetch)
        assert calls == [1, 2]
        assert result == [{"x": 1}, {"x": 2}]

    def test_stops_on_empty_results(self):
        pages = {
            1: _mk_envelope([{"a": 1}]),
            2: _mk_envelope([]),
        }

        def fetch(n):
            return pages[n]

        result = paginate(fetch)
        assert result == [{"a": 1}]

    def test_max_pages_cap(self, caplog):
        def fetch(n):
            return _mk_envelope([{"n": n}], next_url=f"?page={n + 1}")

        with caplog.at_level(logging.WARNING):
            result = paginate(fetch, max_pages=5)
        assert len(result) == 5
        assert "max_pages" in caplog.text.lower()

    def test_propagates_errors(self):
        def fetch(n):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            paginate(fetch)


class TestProbeDefaultPageSize:
    def test_returns_len_of_first_page_results(self):
        def fetch(n):
            assert n == 1
            return _mk_envelope([{"i": i} for i in range(25)])

        assert probe_default_page_size(fetch) == 25
