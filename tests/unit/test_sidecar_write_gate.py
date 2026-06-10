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
