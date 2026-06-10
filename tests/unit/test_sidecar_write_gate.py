import json
import pytest
from sidecar.app import write_gate, ops


def _gate(tmp_path):
    allow = [{"endpoint": "/nextseek_api/samples/", "methods": ["GET"]},
             {"endpoint": "/nextseek_api/samples/advanced_search/", "methods": ["POST"]}]
    p = tmp_path / "rse.json"
    p.write_text(json.dumps(allow))
    class Cfg:  # minimal stand-in for SidecarConfig
        read_safe_endpoints_path = str(p)
    return write_gate.build_gate(Cfg())


def test_read_safe_allows_listed(tmp_path):
    g = _gate(tmp_path)
    g("api-read", "/nextseek_api/samples/", "GET", False)  # no raise


def test_read_not_in_allowlist_blocks(tmp_path):
    g = _gate(tmp_path)
    with pytest.raises(ops.WriteBlockedError):
        g("api-read", "/nextseek_api/projects/", "GET", False)


def test_write_requires_boolean_true(tmp_path):
    g = _gate(tmp_path)
    with pytest.raises(ops.WriteBlockedError):
        g("api-write", None, None, False)
    with pytest.raises(ops.WriteBlockedError):
        g("api-write", None, None, "true")  # string truthy is NOT confirmation (§8)
    g("api-write", None, None, True)  # ok


def test_missing_allowlist_is_config_error(tmp_path):
    class Cfg:
        read_safe_endpoints_path = str(tmp_path / "nope.json")
    with pytest.raises(write_gate.AllowlistMissingError):
        write_gate.build_gate(Cfg())


def test_other_ops_pass_through(tmp_path):
    """entity/parse/graph/report/generate-submission are read-class — gate allows them."""
    g = _gate(tmp_path)
    for op in ("entity", "parse", "graph", "report", "generate-submission"):
        g(op, None, None, False)  # must not raise


# Fix 1 — default-deny: unknown op labels raise WriteBlockedError
def test_unknown_op_raises(tmp_path):
    """Any op label not in SIDECAR_OPS must raise WriteBlockedError (default-deny)."""
    g = _gate(tmp_path)
    for bad_op in ("API-WRITE", "write", "READ", "", "unknown"):
        with pytest.raises(ops.WriteBlockedError, match="unknown op for write gate"):
            g(bad_op, None, None, False)


def test_read_class_ops_do_not_raise(tmp_path):
    """Each of the five read-class ops returns None without raising."""
    g = _gate(tmp_path)
    for op in ("entity", "parse", "graph", "report", "generate-submission"):
        result = g(op, None, None, False)
        assert result is None


# Fix 2 — typed allowlist load failures
def test_corrupt_allowlist_raises_typed_error(tmp_path):
    """A file containing invalid JSON raises AllowlistMissingError, not json.JSONDecodeError."""
    p = tmp_path / "rse.json"
    p.write_text("{not json")

    class Cfg:
        read_safe_endpoints_path = str(p)

    with pytest.raises(write_gate.AllowlistMissingError, match="unusable"):
        write_gate.build_gate(Cfg())


def test_malformed_shape_raises_typed_error(tmp_path):
    """A JSON object (not a list) raises AllowlistMissingError."""
    p = tmp_path / "rse.json"
    p.write_text(json.dumps({"endpoint": "x"}))

    class Cfg:
        read_safe_endpoints_path = str(p)

    with pytest.raises(write_gate.AllowlistMissingError, match="malformed"):
        write_gate.build_gate(Cfg())


# Fix 3 — method case-insensitivity regression pin
def test_method_case_insensitive(tmp_path):
    """Lowercase method string is normalised to uppercase by the gate."""
    g = _gate(tmp_path)
    g("api-read", "/nextseek_api/samples/", "get", False)  # must not raise
