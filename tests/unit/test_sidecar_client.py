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
    def recv(self, timeout=None): return self._response
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


# ---------------------------------------------------------------------------
# Important-1: recv timeout
# ---------------------------------------------------------------------------

class TimeoutFakeWS:
    """A FakeWS that asserts a non-None timeout was passed to recv()."""
    def __init__(self): self.recv_timeout = "NOT_CALLED"
    def send(self, msg): pass
    def recv(self, timeout=None):
        self.recv_timeout = timeout
        return json.dumps({"request_id": "X", "status": "ok", "result": {}, "error": None})
    def close(self): pass


def test_recv_called_with_non_none_timeout(monkeypatch):
    """Important-1: ws.recv() must be called with a non-None timeout to prevent hangs."""
    fake = TimeoutFakeWS()
    monkeypatch.setattr(sc, "_connect", lambda url: fake)
    sc.call_op("entity", {"query": "q"}, ns_login=("u", "p"),
               sidecar_url="ws://x:8765", request_id="X")
    assert fake.recv_timeout is not None, (
        f"recv() was called with timeout=None; expected a finite timeout, got {fake.recv_timeout!r}"
    )


class TimeoutErrorFakeWS:
    """A FakeWS whose recv() raises TimeoutError (simulates a stalled sidecar)."""
    def send(self, msg): pass
    def recv(self, timeout=None): raise TimeoutError("recv timed out")
    def close(self): pass


def test_recv_timeout_error_becomes_transport_error(monkeypatch):
    """Important-1: TimeoutError from recv() must surface as TRANSPORT_ERROR/exit 7."""
    monkeypatch.setattr(sc, "_connect", lambda url: TimeoutErrorFakeWS())
    with pytest.raises(sc.SidecarCallError) as ei:
        sc.call_op("entity", {"query": "q"}, ns_login=("u", "p"), sidecar_url="ws://x:8765")
    assert ei.value.code == "TRANSPORT_ERROR" and ei.value.exit_code == 7


# ---------------------------------------------------------------------------
# Minor-4: non-dict JSON response → TRANSPORT_ERROR
# ---------------------------------------------------------------------------

class NonDictFakeWS:
    """FakeWS that returns valid JSON but not an object (e.g. a bare integer)."""
    def __init__(self, payload): self._payload = payload
    def send(self, msg): pass
    def recv(self, timeout=None): return self._payload
    def close(self): pass


@pytest.mark.parametrize("payload", ["123", "[]", '"string"', "null"])
def test_non_dict_json_response_raises_transport_error(monkeypatch, payload):
    """Minor-4: valid non-object JSON must raise TRANSPORT_ERROR, not AttributeError."""
    monkeypatch.setattr(sc, "_connect", lambda url: NonDictFakeWS(payload))
    with pytest.raises(sc.SidecarCallError) as ei:
        sc.call_op("entity", {"query": "q"}, ns_login=("u", "p"), sidecar_url="ws://x:8765")
    assert ei.value.code == "TRANSPORT_ERROR" and ei.value.exit_code == 7
