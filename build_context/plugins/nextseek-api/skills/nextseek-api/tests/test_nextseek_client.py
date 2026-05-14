"""Tests for the sync NextseekClient port.

Uses httpx.MockTransport(handler) to simulate responses deterministically.
Tests cover: happy path GET, auth error (no retry), 5xx retry with backoff,
retry exhaustion, timeout retry, immediate auth-fail, and env-var precedence.

NOTE (Task 5R verification-gap closure): the ``TestPreflight`` cases below
mock specific response codes at a hardcoded URL; they do NOT verify that the
default ``schema_path`` of ``preflight_schema`` actually points to a real
route on NExtSEEK. That gap is closed by
``test_preflight_default_schema_path_resolves_to_live_route`` which asserts
the default, when canonicalized + joined to a base URL, produces the known
auth-guarded ``/nextseek_api/schema/?format=yaml`` path.
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest import mock

import httpx
import pytest
import respx

from lib.nextseek_client import (
    NextseekAPIError,
    NextseekAuthError,
    NextseekClient,
    NextseekConfig,
    NextseekTimeoutError,
    PreflightResult,
    preflight_schema,
)


# ─── helpers ──────────────────────────────────────────────────────


def _make_client(
    handler,
    *,
    max_retries: int = 3,
    base_url: str = "https://nextseek-test.example.com/nextseek_api",
    username: str = "alice",
    password: str = "secret",
) -> NextseekClient:
    """Build a NextseekClient wired to a MockTransport handler."""
    config = NextseekConfig(
        base_url=base_url,
        username=username,
        password=password,
        timeout=1.0,
        max_retries=max_retries,
    )
    transport = httpx.MockTransport(handler)
    return NextseekClient(config=config, transport=transport)


def _json_response(status: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload).encode("utf-8"),
                          headers={"content-type": "application/json"})


# ─── tests ────────────────────────────────────────────────────────


def test_basic_get_returns_json() -> None:
    """Happy path: mock transport returns 200 + JSON; client returns dict."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("authorization", "")
        return _json_response(200, {"samples": ["A1", "B2"], "count": 2})

    with _make_client(handler) as client:
        result = client.get("samples/", params={"project_id": "SRP"})

    assert result == {"samples": ["A1", "B2"], "count": 2}
    assert captured["method"] == "GET"
    assert "project_id=SRP" in captured["url"]
    assert captured["auth_header"].startswith("Basic ")  # HTTP Basic auth set


def test_401_raises_auth_error() -> None:
    """401 response raises NextseekAuthError with status_code attr."""
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(401, {"detail": "Invalid credentials"})

    with _make_client(handler) as client:
        with pytest.raises(NextseekAuthError) as exc_info:
            client.get("samples/")

    assert exc_info.value.status_code == 401
    assert "401" in str(exc_info.value)


def test_500_retries_with_backoff() -> None:
    """Transport returns 500 twice then 200; client retries and returns final result."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return _json_response(500, {"error": "internal"})
        return _json_response(200, {"ok": True})

    with mock.patch("lib.nextseek_client.time.sleep") as sleep_mock:
        with _make_client(handler, max_retries=3) as client:
            result = client.get("samples/")

    assert result == {"ok": True}
    assert call_count["n"] == 3
    # Two retries => two sleep calls at 2**0=1 and 2**1=2 seconds
    assert sleep_mock.call_count == 2
    sleep_mock.assert_any_call(1)
    sleep_mock.assert_any_call(2)


def test_500_exhausts_retries() -> None:
    """Transport returns 500 every time; client raises NextseekAPIError after max_retries."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _json_response(500, {"error": "always broken"})

    with mock.patch("lib.nextseek_client.time.sleep"):
        with _make_client(handler, max_retries=3) as client:
            with pytest.raises(NextseekAPIError) as exc_info:
                client.get("samples/")

    assert exc_info.value.status_code == 500
    assert exc_info.value.response_body == {"error": "always broken"}
    # 1 initial + 3 retries = 4 total attempts
    assert call_count["n"] == 4


def test_timeout_retries() -> None:
    """httpx.TimeoutException retries up to max_retries, then raises NextseekTimeoutError."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return _json_response(200, {"ok": True})

    with mock.patch("lib.nextseek_client.time.sleep") as sleep_mock:
        with _make_client(handler, max_retries=3) as client:
            result = client.get("samples/")

    assert result == {"ok": True}
    assert call_count["n"] == 3
    assert sleep_mock.call_count == 2  # retried twice before success


def test_auth_error_never_retries() -> None:
    """401 on first attempt raises immediately — no retries, no sleep."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return _json_response(401, {"detail": "nope"})

    with mock.patch("lib.nextseek_client.time.sleep") as sleep_mock:
        with _make_client(handler, max_retries=5) as client:
            with pytest.raises(NextseekAuthError):
                client.get("samples/")

    assert call_count["n"] == 1  # never retried
    assert sleep_mock.call_count == 0


def test_config_from_env_canonical_and_legacy() -> None:
    """NextseekConfig.from_env() honors canonical (NEXTSEEK_BASE_URL/SEEK_USER/SEEK_PASSWORD)
    AND legacy (API_BASE_URL/username/password) names, with canonical taking precedence."""
    # Canonical-only env
    canonical = {
        "NEXTSEEK_BASE_URL": "https://canon.example.com/api",
        "SEEK_USER": "canon-user",
        "SEEK_PASSWORD": "canon-pass",
    }
    with mock.patch.dict(os.environ, canonical, clear=True):
        cfg = NextseekConfig.from_env()
    assert cfg.base_url == "https://canon.example.com/api"
    assert cfg.username == "canon-user"
    assert cfg.password == "canon-pass"

    # Legacy-only env
    legacy = {
        "API_BASE_URL": "https://legacy.example.com/api",
        "username": "legacy-user",
        "password": "legacy-pass",
    }
    with mock.patch.dict(os.environ, legacy, clear=True):
        cfg = NextseekConfig.from_env()
    assert cfg.base_url == "https://legacy.example.com/api"
    assert cfg.username == "legacy-user"
    assert cfg.password == "legacy-pass"

    # Both present: canonical wins
    both = {**legacy, **canonical}
    with mock.patch.dict(os.environ, both, clear=True):
        cfg = NextseekConfig.from_env()
    assert cfg.base_url == "https://canon.example.com/api"
    assert cfg.username == "canon-user"
    assert cfg.password == "canon-pass"


# ─── branch coverage patches ──────────────────────────────────────


def test_request_outside_context_manager_raises() -> None:
    """Calling client methods without `with` raises RuntimeError."""
    client = NextseekClient(
        config=NextseekConfig(base_url="https://x.example.com", username="u", password="p"),
    )
    with pytest.raises(RuntimeError, match="not initialized"):
        client.get("samples/")


def test_non_json_error_response_handled() -> None:
    """500 with HTML body (unparseable as JSON) still raises NextseekAPIError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"<html>down</html>",
                              headers={"content-type": "text/html"})

    with mock.patch("lib.nextseek_client.time.sleep"):
        with _make_client(handler, max_retries=0) as client:
            with pytest.raises(NextseekAPIError) as exc_info:
                client.get("samples/")

    assert exc_info.value.status_code == 500
    assert exc_info.value.response_body is None  # JSON parse failed, body is None


def test_post_with_json_body() -> None:
    """POST method sends the JSON body and returns the response."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return _json_response(200, {"created": True})

    with _make_client(handler) as client:
        result = client.post("samples/", json={"uid": "A1", "project": "SRP"})

    assert result == {"created": True}
    assert captured["method"] == "POST"
    assert captured["body"] == {"uid": "A1", "project": "SRP"}


def test_timeout_exhausts_retries() -> None:
    """Timeout on every attempt raises NextseekTimeoutError after max_retries."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with mock.patch("lib.nextseek_client.time.sleep"):
        with _make_client(handler, max_retries=2) as client:
            with pytest.raises(NextseekTimeoutError):
                client.get("samples/")

    # 1 initial + 2 retries = 3 total attempts
    assert call_count["n"] == 3


def test_is_open_property() -> None:
    """is_open is False before entering context, True inside, False after exiting."""
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, {"ok": True})

    client = _make_client(handler)
    assert client.is_open is False
    with client:
        assert client.is_open is True
    assert client.is_open is False


# ─── task-01: preflight_schema ────────────────────────────────────


@pytest.fixture
def preflight_config() -> NextseekConfig:
    return NextseekConfig(
        base_url="https://nextseek.mit.edu/nextseek_api",
        username="alice",
        password="secret",
        timeout=1.0,
    )


class TestPreflight:
    def test_200_diagnosed_as_ok(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(return_value=httpx.Response(200, json={"schema": "ok"}))
            result = preflight_schema(preflight_config)
        assert result.ok is True
        assert result.diagnosis == "ok"

    def test_403_html_body_diagnosed_as_bad_url(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(return_value=httpx.Response(
                403,
                headers={"Content-Type": "text/html"},
                text="<html>Not Found</html>",
            ))
            result = preflight_schema(preflight_config)
        assert result.ok is False
        assert result.diagnosis == "bad-url"

    def test_403_json_diagnosed_as_bad_auth(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(return_value=httpx.Response(
                403,
                headers={"Content-Type": "application/json"},
                json={"detail": "Authentication credentials were not provided."},
            ))
            result = preflight_schema(preflight_config)
        assert result.ok is False
        assert result.diagnosis == "bad-auth"

    def test_401_json_diagnosed_as_bad_auth(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(return_value=httpx.Response(
                401,
                headers={"Content-Type": "application/json"},
                json={"detail": "bad creds"},
            ))
            result = preflight_schema(preflight_config)
        assert result.diagnosis == "bad-auth"

    def test_500_diagnosed_as_other(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(return_value=httpx.Response(500, text="boom"))
            result = preflight_schema(preflight_config)
        assert result.ok is False
        assert result.diagnosis == "other"

    def test_network_error_diagnosed_as_network(self, preflight_config):
        with respx.mock(assert_all_called=False) as rmock:
            rmock.get(
                "https://nextseek.mit.edu/nextseek_api/schema/?format=yaml",
            ).mock(side_effect=httpx.ConnectError("boom"))
            result = preflight_schema(preflight_config)
        assert result.ok is False
        assert result.diagnosis == "network"

    def test_preflight_result_dataclass_shape(self):
        r = PreflightResult(True, "https://x", "ok", "")
        assert r.ok is True
        assert r.resolved_url == "https://x"
        assert r.diagnosis == "ok"

    def test_preflight_default_schema_path_resolves_to_live_route(
        self, preflight_config
    ):
        """Regression (Task 5R): the default ``schema_path`` must canonicalize
        + join with the base URL to produce the known auth-guarded live route
        ``/nextseek_api/schema/?format=yaml``.

        Live probe (2026-04, dev, demo:demopassword BasicAuth):
          - ``schema_rag/schema/`` → 404 HTML  (the previous default — broken)
          - ``schema/?format=yaml`` → 200    (current default — correct)

        This test catches:
          (1) default-path drift in ``preflight_schema``; and
          (2) any canonicalization bug that would strip or rewrite the path.
        """
        from urllib.parse import urlsplit

        import inspect

        # (1) Static default-drift guard.
        sig = inspect.signature(preflight_schema)
        default_schema_path = sig.parameters["schema_path"].default
        assert default_schema_path == "schema/?format=yaml", (
            f"preflight_schema default schema_path drifted to "
            f"{default_schema_path!r}; must be 'schema/?format=yaml' to hit "
            f"the live auth-guarded NExtSEEK route."
        )

        # (2) Functional guard — intercept the actual URL preflight_schema
        # builds and assert its path component matches the live route.
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"schema": "ok"})

        with respx.mock(assert_all_called=True) as rmock:
            rmock.get().mock(side_effect=handler)
            result = preflight_schema(preflight_config)

        assert result.ok is True
        split = urlsplit(captured["url"])
        assert split.path == "/nextseek_api/schema/", (
            f"preflight URL path={split.path!r} — expected "
            f"'/nextseek_api/schema/' (the auth-guarded live route)."
        )
        assert split.query == "format=yaml", (
            f"preflight URL query={split.query!r} — expected 'format=yaml'."
        )


def test_request_method_generic() -> None:
    """Generic .request() method works for arbitrary methods."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return _json_response(200, {"ok": True})

    with _make_client(handler) as client:
        result = client.request("GET", "ping/", headers={"X-Trace": "abc"})

    assert result == {"ok": True}
    assert captured["method"] == "GET"


# ─── task-03: enriched error context + formatting ─────────────────


class TestAPIErrorFormatting:
    """NextseekAPIError.__str__ renders status, method, URL, and body together (#13)."""

    def test_str_contains_all_context(self) -> None:
        err = NextseekAPIError(
            "API error: 404",
            status_code=404,
            method="GET",
            resolved_url="https://nextseek.mit.edu/nextseek_api/assays/bad/",
            response_body={"detail": "Not found."},
        )
        s = str(err)
        assert "404" in s
        assert "GET" in s
        assert "nextseek.mit.edu/nextseek_api/assays/bad/" in s
        assert "Not found." in s

    def test_str_truncates_long_body(self) -> None:
        body = "X" * 5000
        err = NextseekAPIError(
            "oops",
            status_code=404,
            method="GET",
            resolved_url="http://x/y",
            response_body=body,
        )
        s = str(err)
        assert len(s) < 3000  # truncated
        assert "…" in s or "truncated" in s.lower()

    def test_str_omits_missing_method_and_url(self) -> None:
        """If method/resolved_url are blank, __str__ gracefully omits them."""
        err = NextseekAPIError("oops", status_code=500)
        s = str(err)
        assert "500" in s
        # No method/url fragment when blank
        assert "GET" not in s
        assert "http" not in s

    def test_str_omits_body_when_none(self) -> None:
        err = NextseekAPIError(
            "oops",
            status_code=500,
            method="POST",
            resolved_url="http://x/y",
            response_body=None,
        )
        s = str(err)
        assert "500" in s
        assert "POST" in s
        assert "http://x/y" in s


class TestClientEnrichesError:
    """_request() populates method + resolved_url on raised NextseekAPIError (#13)."""

    def test_404_raises_with_full_context(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(404, {"detail": "x"})

        with _make_client(handler, max_retries=0) as client:
            with pytest.raises(NextseekAPIError) as exc_info:
                client.get("missing/")

        err = exc_info.value
        assert err.status_code == 404
        assert err.method == "GET"
        assert err.resolved_url.endswith("/missing/")
        assert "missing/" in err.resolved_url

    def test_500_retry_exhausted_still_enriched(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(500, {"error": "boom"})

        with mock.patch("lib.nextseek_client.time.sleep"):
            with _make_client(handler, max_retries=1) as client:
                with pytest.raises(NextseekAPIError) as exc_info:
                    client.post("samples/", json={"a": 1})

        err = exc_info.value
        assert err.status_code == 500
        assert err.method == "POST"
        assert err.resolved_url.endswith("/samples/")
