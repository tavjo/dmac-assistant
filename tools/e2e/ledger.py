"""Pre-call spend ledger with ceiling enforcement (T18, F-T18-3).

Every paid sidecar op registers a projected cost BEFORE invocation. If the
running total would exceed the per-session cap, the call is refused by raising
LedgerCeilingError — the call is never made.  After the call, the actual token
counts replace the projection.

Usage (orchestrator paid run):

    ledger = SpendLedger(session_cap_usd=5.00)
    ledger.reserve("entity", model="gemini-3.5-flash", projected_usd=0.10)
    # ... call the op ...
    ledger.record("entity", model="gemini-3.5-flash", in_tokens=52021, out_tokens=89,
                  actual_usd=0.079)
    ledger.save(path)   # writes JSONL ledger + reconciliation text

Hermetic unit tests live in tests/unit/test_t18_ledger_ceiling.py.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class LedgerCeilingError(RuntimeError):
    """Raised before a paid call that would push the ledger over the cap.

    The call is NEVER made when this is raised — no LLM spend occurred.
    """

    def __init__(self, op: str, projected_usd: float, running_usd: float, cap_usd: float) -> None:
        self.op = op
        self.projected_usd = projected_usd
        self.running_usd = running_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"[LEDGER CEILING] refusing '{op}': "
            f"projected ${projected_usd:.4f} + running ${running_usd:.4f} = "
            f"${projected_usd + running_usd:.4f} > cap ${cap_usd:.2f}"
        )


@dataclass
class LedgerEntry:
    op: str
    model: str
    projected_usd: float
    actual_usd: float | None = None
    in_tokens: int | None = None
    out_tokens: int | None = None
    status: str = "reserved"   # "reserved" | "settled" | "refused"
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SpendLedger:
    """Thread-safe running spend ledger with a hard pre-call ceiling.

    Args:
        session_cap_usd: Abort (raise LedgerCeilingError) before any call
            that would push the cumulative spend over this limit.
    """

    def __init__(self, session_cap_usd: float = 5.00) -> None:
        self._cap = session_cap_usd
        self._entries: list[LedgerEntry] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface

    @property
    def running_usd(self) -> float:
        """Sum of all settled actual_usd (reserved-but-not-yet-settled entries
        use their projected_usd as a conservative upper bound)."""
        with self._lock:
            return self._running_usd()

    def reserve(self, op: str, *, model: str, projected_usd: float) -> None:
        """Check the ceiling and mark the op as reserved.

        Raises LedgerCeilingError BEFORE the call if adding `projected_usd`
        to the current running total would exceed the session cap.  The error
        is the caller's signal that NO LLM call should be made.
        """
        with self._lock:
            running = self._running_usd()
            if running + projected_usd > self._cap:
                entry = LedgerEntry(
                    op=op, model=model, projected_usd=projected_usd,
                    actual_usd=None, status="refused",
                )
                self._entries.append(entry)
                raise LedgerCeilingError(op, projected_usd, running, self._cap)
            self._entries.append(
                LedgerEntry(op=op, model=model, projected_usd=projected_usd)
            )

    def record(
        self,
        op: str,
        *,
        model: str,
        in_tokens: int,
        out_tokens: int,
        actual_usd: float,
    ) -> None:
        """Settle a previously reserved entry with actual token counts + cost.

        Finds the most recent 'reserved' entry matching (op, model) and marks
        it settled.  If no reserved entry is found, appends a new settled entry
        (defensive: lets callers record unexpected ops without crashing).
        """
        with self._lock:
            for entry in reversed(self._entries):
                if entry.op == op and entry.model == model and entry.status == "reserved":
                    entry.actual_usd = actual_usd
                    entry.in_tokens = in_tokens
                    entry.out_tokens = out_tokens
                    entry.status = "settled"
                    return
            # No matching reserved entry — append a new settled row.
            self._entries.append(
                LedgerEntry(
                    op=op, model=model,
                    projected_usd=actual_usd, actual_usd=actual_usd,
                    in_tokens=in_tokens, out_tokens=out_tokens,
                    status="settled",
                )
            )

    def save(self, path: Path) -> None:
        """Write JSONL ledger + human-readable reconciliation text to `path`.

        `path` is the JSONL file; a sibling `<path.stem>_reconciliation.txt`
        is also written in the same directory.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            entries = list(self._entries)
        with path.open("w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(asdict(e)) + "\n")
        # Human-readable reconciliation.
        rec_path = path.parent / f"{path.stem}_reconciliation.txt"
        settled = [e for e in entries if e.status == "settled" and e.actual_usd is not None]
        total = sum(e.actual_usd for e in settled)  # type: ignore[arg-type]
        lines = [
            f"COST RECONCILIATION — T18 rewired-path E2E",
            f"cap=${self._cap:.2f}  entries={len(entries)}  settled={len(settled)}",
            "",
            f"{'model':<42} {'in':>8} {'out':>6} {'$':>10}",
            "-" * 68,
        ]
        for e in settled:
            lines.append(
                f"{e.model:<42} {(e.in_tokens or 0):>8} {(e.out_tokens or 0):>6} "
                f"{e.actual_usd:>10.6f}"
            )
        lines += ["-" * 68, f"TOTAL {total:>52.6f}", "", f"cap=${self._cap:.2f}  WITHIN CAP: {total <= self._cap}"]
        rec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Private

    def _running_usd(self) -> float:
        """Sum of costs from all non-refused entries (settled=actual, reserved=projected)."""
        total = 0.0
        for e in self._entries:
            if e.status == "refused":
                continue
            if e.status == "settled" and e.actual_usd is not None:
                total += e.actual_usd
            elif e.status == "reserved":
                total += e.projected_usd
        return total
