"""Sync HTTP client for the NExtSEEK REST API.

Ported from T2Viz's async NextseekClient at
/Users/taishajoseph/Documents/Projects/T2Viz/src/clients/nextseek_client.py

Changes from T2Viz:
- Uses httpx.Client (not AsyncClient)
- Uses time.sleep (not asyncio.sleep)
- __enter__/__exit__ instead of __aenter__/__aexit__
- Methods are plain `def` (not `async def`)
- NextseekConfig.from_env() honors legacy env var names (API_BASE_URL,
  BASE_URL, username, password) in addition to canonical
  (NEXTSEEK_BASE_URL, SEEK_USER, SEEK_PASSWORD) — see DD-07. Full
  loader with .env file reading + USE_DEV_API toggle lives in task-03's
  lib/env_loader.py; this from_env() is a light-touch shim so the
  client is usable standalone in tests.

Preserves:
- The exact error class hierarchy (NextseekClientError,
  NextseekAuthError, NextseekAPIError, NextseekTimeoutError)
- HTTP Basic auth via httpx.BasicAuth
- Exponential backoff retry on 5xx and timeouts (2**attempt seconds)
- Never-retry-on-auth behavior
- get/post/request method surface
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ─── Error hierarchy ──────────────────────────────────────────────


class NextseekClientError(Exception):
    """Base exception for all NExtSEEK client errors."""


class NextseekAuthError(NextseekClientError):
    """Raised on 401/403 authentication or authorization failures."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class NextseekAPIError(NextseekClientError):
    """Raised on non-auth HTTP error responses (4xx/5xx).

    Carries full request context (method + resolved_url) and the response
    body, formatted into a single-line human-readable ``str()`` for diagnostics.
    See task-03 DD-11 (#13).
    """

    _BODY_TRUNCATE_LIMIT = 2000

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int,
        response_body: object = None,
        method: str = "",
        resolved_url: str = "",
    ) -> None:
        self.status_code = status_code
        self.method = method
        self.resolved_url = resolved_url
        self.response_body = response_body
        super().__init__(message or f"API error: {status_code}")

    def __str__(self) -> str:
        parts: list[str] = [f"[{self.status_code}]"]
        if self.method and self.resolved_url:
            parts.append(f"{self.method} {self.resolved_url}")
        if self.response_body is not None:
            if isinstance(self.response_body, str):
                body_str = self.response_body
            else:
                try:
                    body_str = _json.dumps(self.response_body, default=str)
                except (TypeError, ValueError):
                    body_str = repr(self.response_body)
            if len(body_str) > self._BODY_TRUNCATE_LIMIT:
                body_str = body_str[: self._BODY_TRUNCATE_LIMIT] + "… (truncated)"
            parts.append(f"— {body_str}")
        return " ".join(parts)


class NextseekTimeoutError(NextseekClientError):
    """Raised when an HTTP request times out (after retries exhausted)."""


class SessionExpiredError(NextseekClientError):
    """Raised when the cached SchemaRAG session is past its TTL.

    Introduced by task-02 (DD-15 / issue #17) so ``retrieve()`` can fail
    fast with a human-friendly message before any HTTP call, while still
    allowing ``retrieve_with_auto_ingest()`` to catch the error and trigger
    a one-shot reingest + retry (matching the pre-existing 401 path).
    """

    def __init__(self, message: str = "session expired — run nextseek-init") -> None:
        super().__init__(message)


# ─── Configuration ────────────────────────────────────────────────


@dataclass(frozen=True)
class NextseekConfig:
    """Configuration for the NExtSEEK API client.

    from_env() is a lightweight shim that honors both canonical and
    legacy env var names. Task-03's env_loader.py provides the full
    .env-file-aware loader with USE_DEV_API handling.
    """

    base_url: str = "https://nextseek-dev.mit.edu/nextseek_api"
    username: str = ""
    password: str = ""
    timeout: float = 30.0
    max_retries: int = 3
    # Which env var / source won base-URL resolution. Populated by
    # env_loader.resolve_base_url(); defaults to "" so existing callers
    # (NextseekConfig.from_env, direct construction) do not break.
    base_url_source: str = ""

    @classmethod
    def from_env(cls) -> "NextseekConfig":
        """Load configuration from environment variables.

        Base URL precedence: NEXTSEEK_BASE_URL > API_BASE_URL > BASE_URL > default.
        Credentials precedence: SEEK_USER/SEEK_PASSWORD > username/password.
        """
        base_url = (
            os.environ.get("NEXTSEEK_BASE_URL")
            or os.environ.get("API_BASE_URL")
            or os.environ.get("BASE_URL")
            or cls.base_url  # dataclass default
        )
        username = os.environ.get("SEEK_USER") or os.environ.get("username", "")
        password = os.environ.get("SEEK_PASSWORD") or os.environ.get("password", "")
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            timeout=float(os.environ.get("NEXTSEEK_CLIENT_TIMEOUT", "30.0")),
            max_retries=int(os.environ.get("NEXTSEEK_CLIENT_MAX_RETRIES", "3")),
        )


# ─── Client ───────────────────────────────────────────────────────


class NextseekClient:
    """Sync HTTP client for the NExtSEEK REST API.

    Usage:
        with NextseekClient() as client:
            data = client.get("samples/")
    """

    def __init__(
        self,
        config: NextseekConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config or NextseekConfig.from_env()
        self._transport = transport
        self._client: httpx.Client | None = None

    def __enter__(self) -> "NextseekClient":
        base_url = self._config.base_url.rstrip("/") + "/"
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "auth": httpx.BasicAuth(self._config.username, self._config.password),
            "timeout": httpx.Timeout(self._config.timeout),
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        self._client = httpx.Client(**kwargs)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._client:
            self._client.close()
            self._client = None

    @property
    def is_open(self) -> bool:
        """Whether the underlying HTTP client is initialized and open."""
        return self._client is not None

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a GET request and return the JSON response."""
        return self._request("GET", endpoint, params=params)

    def post(
        self, endpoint: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a POST request with a JSON body and return the response."""
        return self._request("POST", endpoint, json=json)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a request using any supported HTTP method."""
        return self._request(method, endpoint, params=params, json=json, headers=headers)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with retry logic."""
        if self._client is None:
            raise RuntimeError(
                "Client not initialized. Use 'with NextseekClient() as client:'."
            )

        last_error: Exception | None = None
        max_attempts = 1 + self._config.max_retries

        for attempt in range(max_attempts):
            try:
                response = self._client.request(
                    method, endpoint, params=params, json=json, headers=headers,
                )
                return self._handle_response(response)

            except (httpx.TimeoutException, httpx.ReadTimeout) as exc:
                last_error = NextseekTimeoutError(str(exc))
                if attempt < self._config.max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "request_timeout",
                        extra={"attempt": attempt + 1, "delay": delay, "endpoint": endpoint},
                    )
                    time.sleep(delay)
                    continue
                raise last_error from exc

            except NextseekAuthError:
                raise  # Never retry auth failures

            except NextseekAPIError as exc:
                if exc.status_code >= 500 and attempt < self._config.max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "server_error_retry",
                        extra={"attempt": attempt + 1, "status": exc.status_code, "delay": delay},
                    )
                    time.sleep(delay)
                    last_error = exc
                    continue
                raise

        if last_error is None:
            raise NextseekClientError(
                "Request failed with no error captured after retries."
            )
        raise last_error

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse response, raising typed errors for non-2xx status codes."""
        if response.is_success:
            return response.json()

        try:
            body = response.json()
        except Exception:
            body = None

        if response.status_code in (401, 403):
            raise NextseekAuthError(
                f"Authentication failed: {response.status_code}",
                status_code=response.status_code,
            )

        raise NextseekAPIError(
            f"API error: {response.status_code}",
            status_code=response.status_code,
            response_body=body,
            method=response.request.method,
            resolved_url=str(response.request.url),
        )


# ─── Preflight ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PreflightResult:
    """Result of a preflight probe against a well-known NExtSEEK endpoint.

    ``diagnosis`` is one of: ``"ok"``, ``"bad-url"``, ``"bad-auth"``,
    ``"network"``, ``"other"``.
    """

    ok: bool
    resolved_url: str
    diagnosis: str
    detail: str = ""


def preflight_schema(
    config: NextseekConfig,
    schema_path: str = "schema/?format=yaml",
) -> PreflightResult:
    """GET a well-known auth-guarded API path to verify base URL + creds.

    Unlike ``NextseekClient``, this bypasses the typed error hierarchy so a
    403 with an HTML body (typical for MIT CAS bouncing a bad-URL request)
    can be distinguished from a 403 with a JSON auth error body.
    """
    # Import inside to avoid a circular import between env_loader and this
    # module at module-load time.
    from lib.env_loader import canonicalize_endpoint

    path = canonicalize_endpoint(schema_path)
    url = f"{config.base_url.rstrip('/')}/{path}"
    try:
        with httpx.Client(
            auth=httpx.BasicAuth(config.username, config.password),
            timeout=httpx.Timeout(config.timeout),
        ) as client:
            resp = client.get(url)
    except httpx.RequestError as exc:
        return PreflightResult(False, url, "network", str(exc))

    if resp.status_code == 200:
        return PreflightResult(True, url, "ok")

    if resp.status_code in (401, 403):
        ctype = resp.headers.get("content-type", "")
        body = resp.text[:256]
        if "html" in ctype.lower() or "<html" in body.lower():
            return PreflightResult(False, url, "bad-url", body)
        return PreflightResult(False, url, "bad-auth", body)

    return PreflightResult(
        False,
        url,
        "other",
        f"{resp.status_code}: {resp.text[:256]}",
    )
