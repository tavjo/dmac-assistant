"""
T5 — N3 enum-spelling sync gate.

Verifies that the BAML output enum literals in baml_src/judge_ui.baml
match T2's Pydantic JUDGE_VERDICT_LITERALS exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.e2e.schema import JUDGE_VERDICT_LITERALS


BAML_PATH = Path(__file__).resolve().parents[2] / "baml_src" / "judge_ui.baml"


@pytest.mark.parametrize("verdict", JUDGE_VERDICT_LITERALS)
def test_each_t2_verdict_appears_in_judge_baml(verdict: str) -> None:
    """N3 sync gate: each T2 lowercase literal must appear as a BAML @alias value
    (not merely anywhere in the file — comments and docstrings would otherwise
    let alias typos slip through)."""
    if not BAML_PATH.exists():
        pytest.skip("judge.baml not yet authored — run during T5 GREEN phase")
    text = BAML_PATH.read_text()
    pattern = rf'@alias\(\s*"{re.escape(verdict)}"\s*\)'
    assert re.search(pattern, text), (
        f"verdict literal {verdict!r} not found as a BAML @alias value in judge.baml "
        f"— N3 sync gate violated (substring presence is insufficient)"
    )


def test_judge_baml_does_not_smuggle_chat_nextseek_score_enum() -> None:
    """chat_nextseek's Score enum is {PASS, PARTIAL, FAIL}. Our enum is lowercase
    and disjoint. Detect accidental copy-paste from chat_nextseek's evaluator."""
    if not BAML_PATH.exists():
        pytest.skip("judge.baml not yet authored")
    text = BAML_PATH.read_text()
    # Our verdict enum is lowercase singular words; chat_nextseek's Score uses
    # uppercase PASS/PARTIAL/FAIL. The enum block in judge.baml must NOT contain
    # those uppercase literals as enum values.
    for forbidden in ("PASS\n", "PARTIAL\n", "FAIL\n"):
        assert forbidden not in text, (
            f"chat_nextseek Score-style literal {forbidden.strip()!r} found in judge.baml"
        )
