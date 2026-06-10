"""WS request/response schemas + the fixed error-code→exit-code map (OD-1, §12)."""
import pytest

from sidecar.app import contract as ws


def test_seven_sidecar_ops_only():
    assert ws.SIDECAR_OPS == frozenset(
        {"entity", "parse", "api-read", "api-write", "graph", "report", "generate-submission"}
    )


def test_error_code_exit_map_is_fixed():
    assert ws.ERROR_EXIT == {
        "CONFIG_MISSING": 2, "IMPORT_FAILED": 2, "VALIDATION": 3,
        "AGENT_FAILED": 4, "WRITE_BLOCKED": 5, "CONFIG_ERROR": 6,
        "TRANSPORT_ERROR": 7, "AUTH_FAILED": 8, "STAGING_ERROR": 9,
    }


def test_request_validates_and_rejects_unknown_op():
    req = ws.SidecarRequest(op="entity", args={"query": "x"},
                            ns_login=ws.NsLogin(api_user="u", api_pass="p"),
                            request_id="11111111-1111-4111-8111-111111111111")
    assert req.op == "entity"
    with pytest.raises(ValueError):
        ws.SidecarRequest(op="query", args={}, ns_login=ws.NsLogin(api_user="u", api_pass="p"),
                          request_id="11111111-1111-4111-8111-111111111111")


def test_request_rejects_extra_fields_and_bad_request_id():
    with pytest.raises(ValueError):
        ws.SidecarRequest(op="entity", args={}, ns_login=ws.NsLogin(api_user="u", api_pass="p"),
                          request_id="not-a-uuid")
    with pytest.raises(ValueError):
        ws.SidecarRequest(op="entity", args={}, ns_login=ws.NsLogin(api_user="u", api_pass="p"),
                          request_id="11111111-1111-4111-8111-111111111111", surprise=1)


def test_response_ok_and_error_shapes():
    ok = ws.SidecarResponse(request_id="11111111-1111-4111-8111-111111111111",
                            status="ok", result={"x": 1}, error=None)
    assert ok.error is None
    err = ws.SidecarResponse(request_id="11111111-1111-4111-8111-111111111111", status="error",
                             result=None, error=ws.SidecarError(code="WRITE_BLOCKED",
                                                                message="m", retryable=False))
    assert ws.ERROR_EXIT[err.error.code] == 5


def test_confirmed_write_is_strict_bool():
    m = ws.ApiWriteArgs(parser_plan="{}", confirmed_write=True)
    assert m.confirmed_write is True
    with pytest.raises(ValueError):
        ws.ApiWriteArgs(parser_plan="{}", confirmed_write="true")


def test_per_op_arg_models_validate_required_fields():
    assert ws.validate_op_args("entity", {"query": "q"}).query == "q"
    with pytest.raises(ValueError):
        ws.validate_op_args("entity", {})
    with pytest.raises(ValueError):
        ws.validate_op_args("report", {"mode": "samples"})
    with pytest.raises(ValueError):
        ws.validate_op_args("report", {"mode": "bogus", "project": "p"})
    with pytest.raises(ValueError):
        ws.validate_op_args("generate-submission", {"type": "GEO"})
    with pytest.raises(ValueError):
        ws.validate_op_args("api-read", {"parser_plan": "{}", "confirmed_write": True})


def test_sidecar_error_rejects_unknown_code():
    with pytest.raises(ValueError):
        ws.SidecarError(code="BOGUS", message="m")


def test_validate_op_args_rejects_bad_submission_type_and_empty_uids():
    with pytest.raises(ValueError):
        ws.validate_op_args("generate-submission", {"type": "BOGUS", "uids": "x"})
    with pytest.raises(ValueError):
        ws.validate_op_args("generate-submission", {"type": "GEO", "uids": "  ,  "})


def test_validate_op_args_unknown_op():
    with pytest.raises(ValueError):
        ws.validate_op_args("not-an-op", {})
