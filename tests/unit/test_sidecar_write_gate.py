"""Write gate tests (T16): simplified no-arg build_gate; only confirmed_write pre-check.
The api-read allowlist has been retired to NExtSEEK; the sidecar's local gate
no longer loads or checks read_safe_endpoints.json."""
import pytest
from sidecar.app import write_gate, ops


def test_build_gate_takes_no_args():
    """build_gate() takes no arguments (T16) — the allowlist arg is gone."""
    gate = write_gate.build_gate()
    assert callable(gate)


def test_api_write_confirmed_true_passes():
    """confirmed_write=True (strict bool) is the only confirmed state."""
    gate = write_gate.build_gate()
    gate("api-write", None, None, True)  # must not raise


def test_api_write_unconfirmed_false_raises():
    gate = write_gate.build_gate()
    with pytest.raises(ops.WriteBlockedError):
        gate("api-write", None, None, False)


def test_api_write_string_true_raises():
    """String 'true' must NOT be treated as confirmed (strict bool only)."""
    gate = write_gate.build_gate()
    with pytest.raises(ops.WriteBlockedError):
        gate("api-write", None, None, "true")


def test_api_write_integer_1_raises():
    """Integer 1 must NOT be treated as confirmed (strict bool only)."""
    gate = write_gate.build_gate()
    with pytest.raises(ops.WriteBlockedError):
        gate("api-write", None, None, 1)


def test_api_read_passes_through():
    """api-read: the local allowlist gate is retired to NExtSEEK (T16); sidecar allows all."""
    gate = write_gate.build_gate()
    gate("api-read", "/any/endpoint/", "GET", False)  # must not raise


def test_read_class_ops_pass_through():
    """entity/parse/graph/report/generate-submission: always allowed locally."""
    gate = write_gate.build_gate()
    for op in ("entity", "parse", "graph", "report", "generate-submission"):
        gate(op, None, None, False)  # must not raise


def test_unknown_op_passes_through():
    """T16: non-api-write ops are allowed (NExtSEEK enforces its own gates)."""
    gate = write_gate.build_gate()
    gate("entity", None, None, False)  # no raise
    gate("some-other-op", None, None, False)  # unknown ops allowed through (NExtSEEK gate)
