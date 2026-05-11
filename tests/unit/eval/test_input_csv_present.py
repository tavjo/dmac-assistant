"""T02: generated input CSV presence + structural smoke test.

This test pins three properties of `data/hibayes_eval_rows.csv`:
1. The file exists.
2. Its header matches `tools.hibayes.exporter.HIBAYES_CSV_COLUMNS` exactly.
3. The row count is > 0.

Per saved memory `feedback_no_test_corpus_in_skill.md`, this test does NOT
assert anything about specific query content; only structural shape.
"""
from __future__ import annotations

import csv
from pathlib import Path

from tools.hibayes.exporter import HIBAYES_CSV_COLUMNS

CSV_PATH = Path(__file__).resolve().parents[3] / "data" / "hibayes_eval_rows.csv"


def test_input_csv_exists() -> None:
    assert CSV_PATH.exists(), (
        f"data/hibayes_eval_rows.csv must exist at {CSV_PATH}; "
        "regenerate via "
        "`uv run python -m tools.hibayes.exporter "
        "evidence/headless/20260507T224850Z/report.html "
        "--output data/hibayes_eval_rows.csv --model-family sonnet`"
    )


def test_input_csv_header_matches_canonical_columns() -> None:
    with CSV_PATH.open("r", newline="") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader))
    assert header == HIBAYES_CSV_COLUMNS, (
        f"CSV header drift: got {header!r}, expected {HIBAYES_CSV_COLUMNS!r}. "
        "Either the exporter changed (out of scope here) or the wrong report "
        "was passed to the generator."
    )


def test_input_csv_has_at_least_one_data_row() -> None:
    with CSV_PATH.open("r", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)  # discard header
        row_count = sum(1 for _ in reader)
    assert row_count > 0, (
        "data/hibayes_eval_rows.csv has zero data rows; the source "
        "evidence/headless/20260507T224850Z/report.html may be malformed."
    )


def test_input_csv_row_count_is_consistent_with_full_test_corpus() -> None:
    """Defeats the 'hand-crafted one-row CSV' gameability described in
    Section 9. The 224850Z bundle was generated from the chat_nextseek
    full_test corpus (103 queries; see saved memory
    `reference_chat_nextseek_test_corpus.md`). Some queries may have errored
    or been filtered, so we assert >=50 rather than ==103 — a fragile pin to
    an exact value would break on any legitimate exporter change. 50 is well
    above what a hand-crafted bypass would produce while leaving slack for
    real-world filtering.
    """
    with CSV_PATH.open("r", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)
        row_count = sum(1 for _ in reader)
    assert row_count >= 50, (
        f"data/hibayes_eval_rows.csv has only {row_count} data rows; "
        "expected >=50 from the 103-query full_test corpus. Either the "
        "exporter is filtering aggressively (investigate) or the CSV was "
        "produced by something other than the canonical exporter run."
    )
