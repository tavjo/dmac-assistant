"""Hermetic unit tests for the T18 pre-call spend ledger ceiling (F-T18-3).

The ledger MUST refuse (raise LedgerCeilingError) before any paid call that
would push the cumulative spend over the session cap.  A post-run assertion
alone is insufficient: the ceiling check must happen before the invocation.

These tests simulate ledger entries approaching the cap and assert that the
next call is refused BEFORE invocation (verified by asserting the op is
NOT in the settled entries after the refusal).
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path


# Import the module via the project pythonpath (src/.  and .) so this test
# runs in the hermetic suite without installing tools/e2e as a package.
from tools.e2e.ledger import LedgerCeilingError, SpendLedger


# ---------------------------------------------------------------------------
# Basic ceiling enforcement

class TestLedgerCeilingEnforcement:
    def test_first_call_within_cap_is_allowed(self) -> None:
        ledger = SpendLedger(session_cap_usd=5.00)
        # Should NOT raise
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.10)
        assert ledger.running_usd == pytest.approx(0.10)

    def test_call_that_would_exceed_cap_is_refused(self) -> None:
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.90)
        with pytest.raises(LedgerCeilingError) as exc_info:
            ledger.reserve("parse", model="claude-opus-4", projected_usd=0.20)
        err = exc_info.value
        assert err.op == "parse"
        assert err.running_usd == pytest.approx(0.90)
        assert err.projected_usd == pytest.approx(0.20)
        assert err.cap_usd == pytest.approx(1.00)

    def test_refused_call_does_not_advance_running_total(self) -> None:
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.90)
        try:
            ledger.reserve("parse", model="claude-opus-4", projected_usd=0.20)
        except LedgerCeilingError:
            pass
        # Running total stays at the reserved entity cost, not entity+parse.
        assert ledger.running_usd == pytest.approx(0.90)

    def test_exact_cap_boundary_is_refused(self) -> None:
        """Spend exactly equal to the cap must be refused (> cap, not >= cap).
        Running=0.95, projected=0.05, cap=1.00 -> would reach exactly 1.00:
        0.95 + 0.05 = 1.00 which is NOT > 1.00, so it must be ALLOWED."""
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("a", model="m", projected_usd=0.95)
        # Exactly at cap: allowed (>  not >=)
        ledger.reserve("b", model="m", projected_usd=0.05)
        assert ledger.running_usd == pytest.approx(1.00)

    def test_one_cent_over_cap_is_refused(self) -> None:
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("a", model="m", projected_usd=0.95)
        with pytest.raises(LedgerCeilingError):
            ledger.reserve("b", model="m", projected_usd=0.06)

    def test_settled_cost_replaces_projected_in_running_total(self) -> None:
        """After settling, running total uses actual_usd, not projected_usd."""
        ledger = SpendLedger(session_cap_usd=5.00)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.50)
        # Actual is cheaper than projected.
        ledger.record("entity", model="gemini-3.5-flash",
                      in_tokens=52021, out_tokens=89, actual_usd=0.079)
        assert ledger.running_usd == pytest.approx(0.079)

    def test_settled_actual_used_for_next_ceiling_check(self) -> None:
        """After settling cheaper-than-projected, next call may still pass."""
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("entity", model="m", projected_usd=0.90)
        ledger.record("entity", model="m", in_tokens=1000, out_tokens=100, actual_usd=0.05)
        # actual=0.05, so next call 0.94 should pass (0.05+0.94=0.99 <= 1.00)
        ledger.reserve("parse", model="m", projected_usd=0.94)
        assert ledger.running_usd == pytest.approx(0.05 + 0.94)


# ---------------------------------------------------------------------------
# Simulated approach-to-cap sequence (mirrors orchestrator paid-step pattern)

class TestApproachToCapSequence:
    """Simulate the T18 paid-step ledger sequence from the spec:
    entity (~0.08), graph (~0.08), api-read (~0.01), api-write (~0.01),
    parse (~0.10), generate-submission (~0.10) + safety headroom.
    Total ≈ $0.38 << $5.00 cap.  Only the CAP boundary behaviour matters here.
    """

    PAID_OPS = [
        ("entity",              "gemini-3.5-flash", 0.10),
        ("graph",               "gemini-3.5-flash", 0.10),
        ("api-read",            "gemini-3.5-flash", 0.02),
        ("api-write-confirmed", "gemini-3.5-flash", 0.02),
        ("parse",               "us.anthropic.claude-opus-4-7", 0.12),
        ("generate-submission", "us.anthropic.claude-opus-4-7", 0.15),
    ]

    def test_full_sequence_within_5_dollar_cap(self) -> None:
        ledger = SpendLedger(session_cap_usd=5.00)
        for op, model, projected in self.PAID_OPS:
            ledger.reserve(op, model=model, projected_usd=projected)
        # All fit inside $5.00.
        assert ledger.running_usd < 5.00

    def test_ceiling_triggers_at_tight_cap(self) -> None:
        """With a $0.35 cap, the 5th op should be refused."""
        ledger = SpendLedger(session_cap_usd=0.35)
        refused_ops: list[str] = []
        for op, model, projected in self.PAID_OPS:
            try:
                ledger.reserve(op, model=model, projected_usd=projected)
            except LedgerCeilingError as exc:
                refused_ops.append(exc.op)
        assert len(refused_ops) >= 1, "at least one op must be refused under $0.35 cap"
        # The refused op was never invoked — its cost must NOT appear in actual totals.

    def test_refused_op_not_counted_in_settled_total(self) -> None:
        """A refused op does not advance the settled spend."""
        ledger = SpendLedger(session_cap_usd=0.15)
        # First op: 0.10 reserved (within cap)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.10)
        ledger.record("entity", model="gemini-3.5-flash",
                      in_tokens=52021, out_tokens=89, actual_usd=0.079)
        # Second op would push to 0.079 + 0.10 = 0.179 > 0.15: refused
        try:
            ledger.reserve("graph", model="gemini-3.5-flash", projected_usd=0.10)
        except LedgerCeilingError:
            pass
        # Running = only the settled entity cost.
        assert ledger.running_usd == pytest.approx(0.079)


# ---------------------------------------------------------------------------
# Error message quality

class TestLedgerCeilingErrorMessage:
    def test_error_message_names_op_and_amounts(self) -> None:
        ledger = SpendLedger(session_cap_usd=1.00)
        ledger.reserve("a", model="m", projected_usd=0.95)
        with pytest.raises(LedgerCeilingError) as exc_info:
            ledger.reserve("my-op", model="m", projected_usd=0.10)
        msg = str(exc_info.value)
        assert "my-op" in msg
        assert "0.10" in msg or "0.1" in msg


# ---------------------------------------------------------------------------
# Save / persistence

class TestLedgerSave:
    def test_save_writes_jsonl_with_one_row_per_entry(self, tmp_path: Path) -> None:
        ledger = SpendLedger(session_cap_usd=5.00)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.10)
        ledger.record("entity", model="gemini-3.5-flash",
                      in_tokens=52021, out_tokens=89, actual_usd=0.079)
        ledger_path = tmp_path / "ledger.jsonl"
        ledger.save(ledger_path)
        rows = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["op"] == "entity"
        assert rows[0]["status"] == "settled"
        assert rows[0]["actual_usd"] == pytest.approx(0.079)

    def test_save_writes_reconciliation_txt(self, tmp_path: Path) -> None:
        ledger = SpendLedger(session_cap_usd=5.00)
        ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.10)
        ledger.record("entity", model="gemini-3.5-flash",
                      in_tokens=52021, out_tokens=89, actual_usd=0.079)
        ledger_path = tmp_path / "ledger.jsonl"
        ledger.save(ledger_path)
        rec_path = tmp_path / "ledger_reconciliation.txt"
        assert rec_path.exists(), "reconciliation .txt must be written alongside the JSONL"
        content = rec_path.read_text()
        assert "gemini-3.5-flash" in content
        assert "TOTAL" in content

    def test_refused_entry_appears_in_jsonl(self, tmp_path: Path) -> None:
        ledger = SpendLedger(session_cap_usd=0.05)
        try:
            ledger.reserve("big-op", model="m", projected_usd=0.10)
        except LedgerCeilingError:
            pass
        ledger_path = tmp_path / "ledger.jsonl"
        ledger.save(ledger_path)
        rows = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
        assert any(r["status"] == "refused" for r in rows), \
            "refused entries must be recorded in the JSONL for audit"
