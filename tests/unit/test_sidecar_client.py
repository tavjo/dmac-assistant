import importlib.util, json, pathlib, sys
import pytest
_BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))
_P = _BIN / "_sidecar_client.py"
_s = importlib.util.spec_from_file_location("_sidecar_client", _P)
sc = importlib.util.module_from_spec(_s); _s.loader.exec_module(sc)


class FakeWS:
    def __init__(self, response): self._response = response; self.sent = None
    def send(self, msg): self.sent = msg
    def recv(self): return self._response
    def close(self): pass


def test_call_op_returns_result(monkeypatch):
    resp = json.dumps({"request_id": "X", "status": "ok", "result": {"v": 1}, "error": None})
    monkeypatch.setattr(sc, "_connect", lambda url: FakeWS(resp))
    # request_id is generated inside; the fake echoes a fixed id, client must not hard-fail on mismatch policy here
    out = sc.call_op("entity", {"query": "q"}, ns_login=("u", "p"),
                     sidecar_url="ws://nextseek-sidecar:8765", request_id="X")
    assert out == {"v": 1}


def test_call_op_error_raises_typed(monkeypatch):
    resp = json.dumps({"request_id": "X", "status": "error", "result": None,
                       "error": {"code": "WRITE_BLOCKED", "message": "no", "retryable": False}})
    monkeypatch.setattr(sc, "_connect", lambda url: FakeWS(resp))
    with pytest.raises(sc.SidecarCallError) as ei:
        sc.call_op("api-write", {"parser_plan": "{}"}, ns_login=("u", "p"),
                   sidecar_url="ws://x:8765", request_id="X")
    assert ei.value.code == "WRITE_BLOCKED" and ei.value.exit_code == 5


def test_transport_failure_is_typed(monkeypatch):
    def boom(url): raise OSError("refused")
    monkeypatch.setattr(sc, "_connect", boom)
    with pytest.raises(sc.SidecarCallError) as ei:
        sc.call_op("entity", {"query": "q"}, ns_login=("u", "p"), sidecar_url="ws://x:8765", request_id="X")
    assert ei.value.code == "TRANSPORT_ERROR" and ei.value.exit_code == 7
