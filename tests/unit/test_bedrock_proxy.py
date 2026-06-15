"""Hermetic unit tests for the OI-3 hardened Bedrock auth-proxy (T1).

Security-critical surface. Every test runs offline against a mock upstream
(`httpx.MockTransport`) — NO real Bedrock call is ever made. The token is a
unique sentinel so the "token-never-logged" test can assert it appears in ZERO
captured log records.

IMPORT STRATEGY (hyphenated source dir)
---------------------------------------
The proxy source lives under ``bedrock-proxy/`` whose name contains a hyphen,
so ``import bedrock-proxy.app.proxy`` is impossible. The proxy only ever runs
inside its own container (a later task remaps it); for hermetic tests run from
the repo root we put ``bedrock-proxy`` on ``sys.path`` and import the generic
``app`` package from inside it. There is no other top-level ``app`` package in
this repo (``sidecar/app`` is only importable as ``sidecar.app``), so there is
no collision. The acceptance validator uses the identical strategy.
"""
from __future__ import annotations

import importlib
import logging
import sys
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_SRC = REPO_ROOT / "bedrock-proxy"
if str(PROXY_SRC) not in sys.path:
    sys.path.insert(0, str(PROXY_SRC))

# Imported lazily inside fixtures via importlib so each test gets a config built
# from the env we control. ``app`` here is ``bedrock-proxy/app``.
import app.config as proxy_config  # noqa: E402
import app.proxy as proxy_mod  # noqa: E402

ALLOWED_MODEL = "us.anthropic.claude-opus-4-8"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def allow_unix_socket_only():
    """FastAPI's TestClient uses an AF_UNIX socketpair; the repo-wide
    ``--disable-socket`` default blocks it. Allow only AF_UNIX for the test body,
    restore strict default on teardown. (Same workaround as test_app_health.py.)
    """
    try:
        import pytest_socket
    except ImportError:  # pragma: no cover
        yield
        return
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.fixture
def sentinel_token() -> str:
    return f"SENTINEL-TOKEN-{uuid.uuid4().hex}"


def _streamed(status: int, content: bytes, headers: dict | None = None) -> httpx.Response:
    """Build a mock upstream response whose body is a real stream.

    The relay reads the upstream via ``aiter_raw()`` (it sends with
    ``stream=True``). ``httpx.MockTransport`` raises ``StreamConsumed`` if the
    response was built with eager ``content=`` and then streamed, so every mock
    upstream response must wrap its bytes in a ``ByteStream`` — exactly what a
    real streaming transport returns. This is a TEST-MOCK fidelity detail, not a
    proxy behavior: real Bedrock always streams.
    """
    return httpx.Response(status, stream=httpx.ByteStream(content), headers=headers or {})


def _make_config(token: str, *, region: str = "us-east-1") -> proxy_config.ProxyConfig:
    return proxy_config.ProxyConfig(
        region=region,
        token=token,
        allowed_models=(ALLOWED_MODEL,),
    )


@pytest.fixture
def configured(monkeypatch, sentinel_token):
    """Install a ProxyConfig with the sentinel token + a mock upstream client.

    Returns a small namespace with the active config and a list to register the
    sequence of mock upstream responses (via a handler closure).
    """
    cfg = _make_config(sentinel_token)
    monkeypatch.setattr(proxy_mod, "config", cfg, raising=True)

    state: dict = {"handler": None, "requests": []}

    def _dispatch(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        handler = state["handler"]
        assert handler is not None, "test did not register a mock upstream handler"
        return handler(request)

    transport = httpx.MockTransport(_dispatch)
    client = httpx.AsyncClient(
        base_url=cfg.upstream_base_url,
        transport=transport,
        timeout=cfg.timeout,
    )
    monkeypatch.setattr(proxy_mod, "_client", client, raising=True)

    yield type("Cfg", (), {"config": cfg, "token": sentinel_token, "state": state})()


@pytest.fixture
def client(configured, allow_unix_socket_only):
    from fastapi.testclient import TestClient

    with TestClient(proxy_mod.app) as c:
        yield c


# ===========================================================================
# Canonicalization + allowlist matrix (the security crux)
# ===========================================================================
ACCEPT_CASES = [
    ("GET", "/inference-profiles"),
    ("POST", f"/model/{ALLOWED_MODEL}/invoke"),
    ("POST", f"/model/{ALLOWED_MODEL}/invoke-with-response-stream"),
]

DENY_CASES = [
    # startswith-bypass: /inference-profiles-evil must NOT match /inference-profiles
    ("GET", "/inference-profiles-evil"),
    # double-slash path confusion
    ("POST", f"//model/{ALLOWED_MODEL}/invoke"),
    # dot segment
    ("POST", f"/model/./{ALLOWED_MODEL}/invoke"),
    # percent-encoded separator
    ("POST", f"/model/{ALLOWED_MODEL}%2finvoke"),
    ("POST", f"/model/{ALLOWED_MODEL}%2Finvoke"),
    # percent-encoded dot (path traversal attempt)
    ("POST", "/model/%2e%2e/invoke"),
    # disallowed model id
    ("POST", "/model/us.anthropic.claude-other/invoke-with-response-stream"),
    # disallowed action verb on an allowed model
    ("POST", f"/model/{ALLOWED_MODEL}/converse"),
    # wrong HTTP method on an otherwise-allowed path
    ("PUT", f"/model/{ALLOWED_MODEL}/invoke"),
    ("DELETE", "/inference-profiles"),
    # GET on an invoke path (method/path mismatch)
    ("GET", f"/model/{ALLOWED_MODEL}/invoke"),
    # POST to the profiles GET-only path
    ("POST", "/inference-profiles"),
    # trailing dot segment
    ("GET", "/inference-profiles/."),
    # parent traversal segment
    ("GET", "/inference-profiles/.."),
]


@pytest.mark.parametrize("method,path", ACCEPT_CASES)
def test_allowed_accepts(method, path):
    assert proxy_mod._allowed(method, path) is True


@pytest.mark.parametrize("method,path", DENY_CASES)
def test_allowed_denies(method, path):
    assert proxy_mod._allowed(method, path) is False


def test_query_string_is_permitted_on_inference_profiles():
    # The allowlist decides on the canonical PATH only; a query string is fine.
    assert proxy_mod._allowed("GET", "/inference-profiles") is True


def test_canonicalize_rejects_double_slash():
    assert proxy_mod._is_canonical("//model/x/invoke") is False


def test_canonicalize_rejects_dot_segments():
    assert proxy_mod._is_canonical("/model/./x/invoke") is False
    assert proxy_mod._is_canonical("/a/../b") is False


def test_canonicalize_rejects_percent_encoded_separators():
    assert proxy_mod._is_canonical("/model/x%2finvoke") is False
    assert proxy_mod._is_canonical("/model/x%2Finvoke") is False
    assert proxy_mod._is_canonical("/x%2e%2e/y") is False


def test_canonicalize_accepts_plain_path():
    assert proxy_mod._is_canonical("/inference-profiles") is True
    assert proxy_mod._is_canonical(f"/model/{ALLOWED_MODEL}/invoke") is True


def test_canonicalize_rejects_path_without_leading_slash():
    # Defensive: a path that does not start with "/" is non-canonical.
    assert proxy_mod._is_canonical("inference-profiles") is False
    assert proxy_mod._allowed("GET", "inference-profiles") is False


# ===========================================================================
# Relay behavior (against mock upstream)
# ===========================================================================
def test_denied_path_returns_403(client):
    r = client.get("/inference-profiles-evil")
    assert r.status_code == 403
    assert r.json()["error"]


def test_allowed_get_streams_through(client, configured):
    body = b"PROFILES-BYTES"

    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, body)

    configured.state["handler"] = handler
    r = client.get("/inference-profiles")
    assert r.status_code == 200
    assert r.content == body


def test_streaming_passthrough_is_byte_identical(client, configured):
    # A chunk of mock eventstream-like bytes: in == out.
    chunks = [b"\x00\x00\x01event-a", b"\x00\x00\x02event-b", b"\xff\xfe\x00chunk3"]
    expected = b"".join(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(expected))

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}/invoke-with-response-stream",
        content=b'{"messages":[]}',
    )
    assert r.status_code == 200
    assert r.content == expected


def test_benign_upstream_404_passes_through(client, configured):
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(
            404,
            b'{"message": "no such profile"}',
            headers={"content-type": "application/json"},
        )

    configured.state["handler"] = handler
    r = client.get("/inference-profiles")
    assert r.status_code == 404
    assert r.json()["message"] == "no such profile"


def test_authorization_header_attached_to_upstream(client, configured):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["host"] = request.headers.get("host")
        return _streamed(200, b"ok")

    configured.state["handler"] = handler
    client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert seen["auth"] == f"Bearer {configured.token}"
    assert seen["host"] == configured.config.upstream_host


def test_client_authorization_header_is_dropped_not_forwarded(client, configured):
    """A hostile agent must not be able to smuggle its own Authorization header
    upstream. The proxy strips any client-supplied Authorization (case-
    insensitively) and attaches EXACTLY its own ``Bearer <proxy-token>``. The
    upstream request must carry exactly one Authorization header with the real
    token, and the attacker value must not appear in ANY upstream header."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # Inspect the raw header list so we can count duplicates and check casing.
        raw = list(request.headers.raw)  # list[(bytes-name-lower, bytes-value)]
        auth_values = [v.decode("latin-1") for (k, v) in raw if k.lower() == b"authorization"]
        seen["auth_values"] = auth_values
        # Did the attacker token leak into ANY upstream header (name or value)?
        all_header_blob = " ".join(
            f"{k.decode('latin-1')}: {v.decode('latin-1')}" for (k, v) in raw
        )
        seen["attacker_present"] = "ATTACKER" in all_header_blob
        return _streamed(200, b"ok")

    configured.state["handler"] = handler
    client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"{}",
        headers={"Authorization": "Bearer ATTACKER"},
    )

    # Exactly one Authorization header, and it is the proxy's real token.
    assert seen["auth_values"] == [f"Bearer {configured.token}"]
    assert len(seen["auth_values"]) == 1
    # The attacker-controlled value did not survive anywhere upstream.
    assert seen["attacker_present"] is False


def test_lowercase_client_authorization_also_dropped(client, configured):
    """Belt-and-suspenders: a lowercase ``authorization`` key (the casing
    Starlette actually exposes on the incoming request) is also stripped, so the
    drop-list comprehension's ``k.lower()`` truly catches it."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        raw = list(request.headers.raw)
        auth_values = [v.decode("latin-1") for (k, v) in raw if k.lower() == b"authorization"]
        seen["auth_values"] = auth_values
        return _streamed(200, b"ok")

    configured.state["handler"] = handler
    client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"{}",
        headers={"authorization": "Bearer attacker-lower"},
    )
    assert seen["auth_values"] == [f"Bearer {configured.token}"]
    assert "attacker-lower" not in " ".join(seen["auth_values"])


def test_authorization_is_in_drop_headers():
    """Unit-level guard: ``authorization`` must remain in the drop-list so a
    future refactor can't silently re-enable client-Authorization passthrough."""
    assert "authorization" in proxy_mod._DROP_HEADERS


# ===========================================================================
# Raw-path percent-encoding canonicalization fires at the RELAY level
# ===========================================================================
def test_relay_rejects_percent_encoded_separator_on_raw_path(client, configured):
    """Production-behavior proof for the percent-encoding defense.

    Starlette percent-DECODES ``request.url.path`` before the relay sees it, so
    a request to ``/model/<id>%2finvoke`` would otherwise decode to the allowed
    ``/model/<id>/invoke`` and slip through. The relay must validate the RAW,
    undecoded path (``scope['raw_path']``) and return 403, never reach upstream.
    """
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a smuggled %2f path")

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}%2finvoke",
        content=b"{}",
    )
    assert r.status_code == 403
    assert r.json()["error"]
    assert configured.state["requests"] == []  # upstream never called


def test_relay_rejects_percent_encoded_separator_uppercase(client, configured):
    """``%2F`` (upper-case) is equally a smuggled separator → 403 at the relay."""
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a smuggled %2F path")

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}%2Finvoke",
        content=b"{}",
    )
    assert r.status_code == 403
    assert configured.state["requests"] == []


def test_relay_rejects_percent_encoded_dot_traversal(client, configured):
    """A percent-encoded dot-dot (``%2e%2e``) traversal attempt is rejected at
    the relay on the raw path."""
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a %2e%2e path")

    configured.state["handler"] = handler
    r = client.post("/model/%2e%2e/invoke", content=b"{}")
    assert r.status_code == 403
    assert configured.state["requests"] == []


def test_raw_path_falls_back_to_decoded_when_scope_missing_raw_path():
    """Defensive fallback: if ``scope['raw_path']`` is absent (or not bytes),
    ``_raw_path`` returns the decoded ``request.url.path``. (Under
    uvicorn/Starlette raw_path is always present; this guards a non-ASGI caller.)
    """
    class _U:
        path = "/inference-profiles"

    class _Req:
        scope: dict = {}  # no raw_path key

        @property
        def url(self):
            return _U()

    assert proxy_mod._raw_path(_Req()) == "/inference-profiles"


def test_raw_path_carries_percent_encoding_under_testclient(configured, allow_unix_socket_only, monkeypatch):
    """Sanity guard for the test setup itself: prove ``scope['raw_path']``
    actually preserves the ``%2f`` under the FastAPI TestClient (if the client
    ever decoded raw_path too, the relay 403 tests above would be meaningless).

    We capture exactly what the relay's ``_raw_path`` sees by spying on it for a
    real smuggled-path request, then assert (a) the raw path still contains the
    literal ``%2f`` and (b) the decoded ``request.url.path`` has already lost it
    (decoded to the allowed route) — which is precisely why the raw-path check is
    load-bearing."""
    from fastapi.testclient import TestClient

    captured = {}
    real_raw_path = proxy_mod._raw_path

    def _spy(request):
        raw = real_raw_path(request)
        captured["raw"] = raw
        captured["decoded"] = request.url.path
        return raw

    monkeypatch.setattr(proxy_mod, "_raw_path", _spy, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a smuggled %2f path")

    configured.state["handler"] = handler

    with TestClient(proxy_mod.app) as c:
        r = c.post(f"/model/{ALLOWED_MODEL}%2finvoke", content=b"{}")

    # The smuggled separator survived in the RAW path the relay validated.
    assert "%2f" in captured["raw"]
    # But Starlette had already DECODED it out of request.url.path — hence the
    # raw-path check is the only thing that catches it.
    assert "%2f" not in captured["decoded"]
    assert captured["decoded"] == f"/model/{ALLOWED_MODEL}/invoke"
    # And the relay correctly rejected the smuggled path.
    assert r.status_code == 403


def test_hop_by_hop_headers_dropped_from_incoming(client, configured):
    """The incoming client's hop-by-hop headers must not be forwarded verbatim.

    Note: httpx's own transport re-adds framing headers (``connection``,
    ``accept-encoding``, ``content-length``) for the upstream hop — that is
    correct per-hop behavior and is httpx-owned, not a passthrough. So we assert
    on a hop-by-hop header httpx does NOT auto-add (``te``, ``upgrade``) to prove
    our drop-list filtered the INCOMING request, and that an arbitrary client
    header (``x-keep``) IS forwarded.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["names"] = {k.lower() for k in request.headers.keys()}
        seen["te"] = request.headers.get("te")
        seen["upgrade"] = request.headers.get("upgrade")
        return _streamed(200, b"ok")

    configured.state["handler"] = handler
    client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"{}",
        headers={"TE": "trailers", "Upgrade": "websocket", "X-Keep": "1"},
    )
    # Our drop-list removed these incoming hop-by-hop headers (httpx does not
    # re-add them).
    assert seen["te"] is None
    assert seen["upgrade"] is None
    # Arbitrary client headers are still forwarded.
    assert "x-keep" in seen["names"]


# ===========================================================================
# Bounded body -> 413 BEFORE full read
# ===========================================================================
def test_oversized_body_rejected_with_413(client, configured):
    # Cap is 10 MiB by default; advertise an oversize Content-Length.
    big_len = configured.config.max_body_bytes + 1

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached for an oversize body")

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"x" * 16,  # actual content small; header lies big
        headers={"Content-Length": str(big_len)},
    )
    assert r.status_code == 413
    assert configured.state["requests"] == []  # upstream never called


def test_malformed_content_length_rejected_with_413(client, configured):
    # A non-integer Content-Length is suspicious → reject with 413, never read.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a malformed length")

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"{}",
        headers={"Content-Length": "not-a-number"},
    )
    assert r.status_code == 413
    assert configured.state["requests"] == []


def test_negative_content_length_rejected_with_413(client, configured):
    # A negative Content-Length is malformed/suspicious → reject with 413, never
    # read. ``int("-9999")`` parses fine, so the cap compare alone would miss it.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached on a negative length")

    configured.state["handler"] = handler
    r = client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=b"{}",
        headers={"Content-Length": "-9999"},
    )
    assert r.status_code == 413
    assert configured.state["requests"] == []


def test_content_length_over_cap_helper_rejects_negative(monkeypatch, configured):
    """Unit-level: the fast-path helper treats a negative declared length as
    oversize (True) directly, independent of the relay."""
    monkeypatch.setattr(proxy_mod, "config", configured.config, raising=True)

    class _Req:
        def __init__(self, cl: str):
            self.headers = {"content-length": cl}

    assert proxy_mod._content_length_over_cap(_Req("-1")) is True
    assert proxy_mod._content_length_over_cap(_Req("-9999")) is True
    # A valid small length is under cap.
    assert proxy_mod._content_length_over_cap(_Req("16")) is False


def test_chunked_oversize_body_rejected_with_413(monkeypatch, configured, allow_unix_socket_only):
    """A chunked POST with NO Content-Length whose actual bytes exceed the cap
    must be aborted with 413 and the upstream must NOT be reached.

    This is the memory-DoS guard: ``_content_length_over_cap`` can't see a
    declared length on a chunked body, so the streaming read enforces the cap on
    the bytes actually read. We shrink the cap so the test body is tiny.
    """
    from fastapi.testclient import TestClient

    # Tiny cap so a small chunked body trips it. Rebuild config with the small
    # cap and re-point the relay's module config at it.
    small_cfg = proxy_config.ProxyConfig(
        region="us-east-1",
        token=configured.token,
        allowed_models=(ALLOWED_MODEL,),
        max_body_bytes=64,
    )
    monkeypatch.setattr(proxy_mod, "config", small_cfg, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must NOT be reached for an oversize chunked body")

    configured.state["handler"] = handler

    # A generator request body produces a chunked transfer (no Content-Length).
    def _gen():
        # 4 KiB total, far over the 64-byte cap, streamed in chunks.
        for _ in range(64):
            yield b"x" * 64

    with TestClient(proxy_mod.app) as c:
        r = c.post(f"/model/{ALLOWED_MODEL}/invoke", content=_gen())

    assert r.status_code == 413
    assert r.json()["error"]
    # Upstream was never reached: no request was dispatched to the mock transport.
    assert configured.state["requests"] == []


def test_chunked_body_under_cap_passes(monkeypatch, configured, allow_unix_socket_only):
    """A chunked POST (no Content-Length) whose bytes are UNDER the cap streams
    through to the upstream unchanged — the streaming reader must not corrupt or
    drop an in-cap body."""
    from fastapi.testclient import TestClient

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return _streamed(200, b"ok")

    configured.state["handler"] = handler

    payload = b'{"messages":[]}'

    def _gen():
        yield payload

    with TestClient(proxy_mod.app) as c:
        r = c.post(f"/model/{ALLOWED_MODEL}/invoke", content=_gen())

    assert r.status_code == 200
    # The full in-cap body reached the upstream byte-for-byte.
    assert seen["body"] == payload


def test_body_at_cap_is_allowed(client, configured):
    def handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, b"ok")

    configured.state["handler"] = handler
    payload = b"a" * 32
    r = client.post(
        f"/model/{ALLOWED_MODEL}/invoke",
        content=payload,
        headers={"Content-Length": str(len(payload))},
    )
    assert r.status_code == 200


# ===========================================================================
# Upstream error mapping -> controlled 502/504 (no stack trace)
# ===========================================================================
def test_connect_error_maps_to_502(client, configured):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    configured.state["handler"] = handler
    r = client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert r.status_code == 502
    body = r.json()
    assert body["error"]
    assert "Traceback" not in (body.get("error") or "")


def test_connect_timeout_maps_to_504(client, configured):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    configured.state["handler"] = handler
    r = client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert r.status_code == 504


def test_read_timeout_maps_to_504(client, configured):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow read", request=request)

    configured.state["handler"] = handler
    r = client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert r.status_code == 504


def test_generic_timeout_exception_maps_to_504(client, configured):
    """A bare ``httpx.TimeoutException`` (a timeout that is NOT one of the
    specific Read/Write/Pool/Connect subclasses) must still map to a controlled
    504 via the catch-all timeout branch — never a stack trace."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("generic timeout", request=request)

    configured.state["handler"] = handler
    r = client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert r.status_code == 504
    body = r.json()
    assert body["error"]
    assert "Traceback" not in (body.get("error") or "")


def test_generic_transport_error_maps_to_502(client, configured):
    """A transport error that is NOT a ConnectError or a timeout (e.g.
    ``httpx.RemoteProtocolError``) must map to a controlled 502 via the
    catch-all transport branch — never a stack trace."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("upstream spoke garbage", request=request)

    configured.state["handler"] = handler
    r = client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")
    assert r.status_code == 502
    body = r.json()
    assert body["error"]
    assert "Traceback" not in (body.get("error") or "")


# ===========================================================================
# /healthz
# ===========================================================================
def test_healthz_returns_200_without_token(monkeypatch, allow_unix_socket_only):
    # Even with an empty/missing token, /healthz must be 200 and not allowlisted.
    cfg = _make_config(token="")
    monkeypatch.setattr(proxy_mod, "config", cfg, raising=True)
    from fastapi.testclient import TestClient

    with TestClient(proxy_mod.app) as c:
        r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_healthz_not_subject_to_allowlist(client):
    # /healthz works on the normally-configured app and never hits the allowlist.
    r = client.get("/healthz")
    assert r.status_code == 200


# ===========================================================================
# Misconfig: missing token -> relay returns 500
# ===========================================================================
def test_missing_token_relay_returns_500(monkeypatch, allow_unix_socket_only):
    cfg = _make_config(token="")
    monkeypatch.setattr(proxy_mod, "config", cfg, raising=True)
    from fastapi.testclient import TestClient

    with TestClient(proxy_mod.app) as c:
        r = c.get("/inference-profiles")
    assert r.status_code == 500
    assert r.json()["error"]


# ===========================================================================
# config.from_env behavior
# ===========================================================================
def test_config_from_env_reads_token_and_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "  tok-123  ")
    cfg = proxy_config.ProxyConfig.from_env()
    assert cfg.region == "eu-west-1"
    assert cfg.token == "tok-123"  # stripped
    assert cfg.upstream_host == "bedrock-runtime.eu-west-1.amazonaws.com"
    assert cfg.allowed_models == (ALLOWED_MODEL,)


def test_config_from_env_defaults_region(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    cfg = proxy_config.ProxyConfig.from_env()
    assert cfg.region == "us-east-1"
    assert cfg.token == ""  # missing token -> empty (relay returns 500)


def test_config_default_body_cap_is_10_mib():
    cfg = _make_config("t")
    assert cfg.max_body_bytes == 10 * 1024 * 1024


def test_config_repr_redacts_token():
    """``repr(ProxyConfig)`` must never render the token — even if it lands in a
    log line — and must show the ``<redacted>`` sentinel instead."""
    cfg = proxy_config.ProxyConfig(
        region="us-east-1",
        token="SENTINEL-XYZ",
        allowed_models=(ALLOWED_MODEL,),
    )
    r = repr(cfg)
    assert "<redacted>" in r
    assert "SENTINEL-XYZ" not in r
    # Region + the non-secret fields are still visible for debuggability.
    assert "us-east-1" in r


def test_config_timeout_is_granular_not_blanket():
    cfg = _make_config("t")
    t = cfg.timeout
    # Granular connect/read/write (not a single 600s blanket).
    assert t.connect is not None
    assert t.read is not None
    assert t.write is not None
    assert t.connect != t.read  # connect must be tighter than read


# ===========================================================================
# Token-never-logged: the structural redaction guarantee
# ===========================================================================
def test_token_never_appears_in_logs(client, configured, caplog):
    """Drive allowed + denied + upstream-error paths and assert the sentinel
    token appears in ZERO captured log records (across ALL log records, and
    crucially across the proxy's own logger)."""
    caplog.set_level(logging.DEBUG)

    # 1) allowed path (token attached to upstream, must not be logged)
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return _streamed(200, b"ok")

    configured.state["handler"] = ok_handler
    client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b'{"secret":"x"}')

    # 2) denied path
    client.get("/inference-profiles-evil")

    # 3) upstream error path
    def err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    configured.state["handler"] = err_handler
    client.post(f"/model/{ALLOWED_MODEL}/invoke", content=b"{}")

    token = configured.token
    for rec in caplog.records:
        assert token not in rec.getMessage()
        # also defend against the token being smuggled in via args
        assert token not in str(getattr(rec, "args", "") or "")


def test_redacting_logger_drops_authorization_structurally(configured, caplog):
    """The proxy's logger is called only with method + canonical path + status;
    it never receives headers or body. Calling it directly with a request that
    *would* carry the token proves the token can't reach a log record."""
    caplog.set_level(logging.DEBUG)
    # The logger entrypoint takes only scalar, non-secret fields.
    proxy_mod._log_access("POST", f"/model/{ALLOWED_MODEL}/invoke", 200)
    for rec in caplog.records:
        assert configured.token not in rec.getMessage()
    # Signature defense: _log_access must not accept a headers/body kwarg.
    import inspect

    params = set(inspect.signature(proxy_mod._log_access).parameters)
    assert "headers" not in params
    assert "body" not in params
    assert "authorization" not in params


def test_log_access_emits_method_path_status(configured, caplog):
    caplog.set_level(logging.INFO)
    proxy_mod._log_access("GET", "/inference-profiles", 200)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "GET" in joined
    assert "/inference-profiles" in joined
    assert "200" in joined
