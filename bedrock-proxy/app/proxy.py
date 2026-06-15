"""OI-3 hardened Bedrock auth-proxy — the relay application (T1).

A singleton FastAPI app that holds the institutional ``AWS_BEARER_TOKEN_BEDROCK``
in its own env and re-attaches it as ``Authorization: Bearer …`` on the way to
Bedrock. The agent container gets ZERO AWS creds; Claude Code emits *unsigned*
Bedrock requests (``CLAUDE_CODE_SKIP_BEDROCK_AUTH=1``) which this proxy
authenticates.

Hardening over the feasibility spike:
  * Exact-match allowlist with **detect-and-reject** canonicalization (no
    normalize-then-accept path confusion). ``startswith`` is gone.
  * Bounded body: 413 BEFORE the body is read into memory.
  * Granular connect/read/write timeouts (config.py), not a 600s blanket.
  * Safe-by-construction redacting logger: structurally cannot receive the
    Authorization header or the body — it takes only method + canonical path +
    status. The token is attached *after* the access-log call site and never
    passed to any logging call.
  * Upstream connect/timeout errors → controlled 502/504 JSON, never a stack
    trace.
  * ``/healthz`` is excluded from auth + the allowlist and returns 200 with no
    token.

The upstream host is fixed from ``AWS_REGION`` at config load (no SSRF).
"""
from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.config import ProxyConfig

# ---------------------------------------------------------------------------
# Module-level config + upstream client. Tests monkeypatch ``config`` and
# ``_client`` to inject a controlled token and an httpx.MockTransport, so the
# import style (module-qualified attributes) is load-bearing.
# ---------------------------------------------------------------------------
config: ProxyConfig = ProxyConfig.from_env()
_client: httpx.AsyncClient = httpx.AsyncClient(
    base_url=config.upstream_base_url,
    timeout=config.timeout,
)

# Hop-by-hop headers (RFC 7230 §6.1) + framing headers we must not forward.
_DROP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "transfer-encoding",
    "accept-encoding",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "upgrade",
}

# ---------------------------------------------------------------------------
# Safe-by-construction redacting logger.
#
# ``_log_access`` accepts ONLY scalar, non-secret fields (method, canonical
# path, status). It has no ``headers``/``body``/``authorization`` parameter, so
# there is structurally no path for the bearer token or the request body to
# reach a log record. The token is attached to the outbound request *after* the
# access-log call and is never passed to any logging function.
# ---------------------------------------------------------------------------
_logger = logging.getLogger("bedrock_proxy.access")


def _log_access(method: str, canonical_path: str, status: int) -> None:
    """Emit a single access line: method + canonical path + status only.

    Structurally cannot emit the Authorization header or the body — neither is
    a parameter. Do NOT add a headers/body parameter to this function.
    """
    _logger.info("%s %s -> %d", method, canonical_path, status)


# ---------------------------------------------------------------------------
# Canonicalization (DETECT-AND-REJECT — never normalize-then-accept).
# ---------------------------------------------------------------------------
def _is_canonical(path: str) -> bool:
    """Return True only if ``path`` is already in canonical form.

    A path is NON-canonical (→ reject) if it contains any of:
      * ``//`` (empty/collapsed segment, e.g. ``//model/x/invoke``)
      * a ``.`` or ``..`` segment (``/./``, ``/../``, trailing ``/.`` / ``/..``)
      * a percent-encoded path separator or dot: ``%2f`` ``%2F`` ``%2e`` ``%2E``
        (case-insensitive) — these are smuggled separators/traversal.

    We do NOT rewrite the path; we reject it. The caller then does an EXACT,
    case-sensitive compare of the clean path against the allowed set.
    """
    if not path.startswith("/"):
        return False
    if "//" in path:
        return False
    # Percent-encoded separators / dots anywhere in the path are illegal here.
    lowered = path.lower()
    if "%2f" in lowered or "%2e" in lowered:
        return False
    # Dot segments.
    segments = path.split("/")
    if any(seg in (".", "..") for seg in segments):
        return False
    return True


def _allowed(method: str, path: str) -> bool:
    """Exact-match allowlist over the canonical path.

    Permits exactly (case-sensitive, exact compare — no ``startswith``):
      * ``GET /inference-profiles``
      * ``POST /model/<id>/invoke`` for each id in ``config.allowed_models``
      * ``POST /model/<id>/invoke-with-response-stream`` for each such id

    Any non-canonical path (``//``, dot segments, percent-encoded separators)
    is rejected outright BEFORE the exact compare. Everything else → False.
    """
    if not _is_canonical(path):
        return False
    if method == "GET":
        return path == "/inference-profiles"
    if method == "POST":
        for model_id in config.allowed_models:
            if path == f"/model/{model_id}/invoke":
                return True
            if path == f"/model/{model_id}/invoke-with-response-stream":
                return True
        return False
    return False


# ---------------------------------------------------------------------------
# FastAPI app.
# ---------------------------------------------------------------------------
app = FastAPI()


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe. Not subject to auth or the allowlist; returns 200 even
    with no token configured."""
    return JSONResponse({"status": "ok"})


def _content_length_over_cap(request: Request) -> bool:
    """True if the declared Content-Length exceeds the cap. Lets us reject with
    413 BEFORE reading the (possibly huge) body into memory."""
    raw = request.headers.get("content-length")
    if raw is None:
        return False
    try:
        declared = int(raw)
    except ValueError:
        # Malformed length: treat as suspicious → reject as oversize.
        return True
    return declared > config.max_body_bytes


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(full_path: str, request: Request) -> Response:
    # ``request.url.path`` preserves the raw, undecoded path so canonicalization
    # can see ``//`` and ``%2f`` etc. (Starlette does not collapse these.)
    canonical_path = request.url.path
    method = request.method

    # 1) Misconfiguration: no token → 500 (as the spike does). Checked before
    #    the allowlist so a misconfigured proxy fails loudly on any real route.
    if not config.token:
        _log_access(method, canonical_path, 500)
        return JSONResponse(
            {"error": "proxy misconfigured: no bearer token"}, status_code=500
        )

    # 2) Allowlist (canonicalize-then-exact-compare). Denied → 403.
    if not _allowed(method, canonical_path):
        _log_access(method, canonical_path, 403)
        return JSONResponse({"error": "path not permitted"}, status_code=403)

    # 3) Bounded body: reject oversize BEFORE reading the body.
    if _content_length_over_cap(request):
        _log_access(method, canonical_path, 413)
        return JSONResponse({"error": "request body too large"}, status_code=413)

    # Body is within cap; safe to read.
    body = await request.body()

    # Build the outbound request. Drop hop-by-hop headers, pin Host, and attach
    # the bearer token LAST. The token is never passed to a logging call.
    fwd_path = canonical_path + (("?" + request.url.query) if request.url.query else "")
    out_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS
    }
    out_headers["Host"] = config.upstream_host
    out_headers["Authorization"] = f"Bearer {config.token}"  # NEVER logged

    upstream_req = _client.build_request(
        method, fwd_path, headers=out_headers, content=body
    )

    try:
        upstream = await _client.send(upstream_req, stream=True)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        _log_access(method, canonical_path, 502 if isinstance(exc, httpx.ConnectError) else 504)
        status = 502 if isinstance(exc, httpx.ConnectError) else 504
        return JSONResponse(
            {"error": "upstream connection failed"}, status_code=status
        )
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        _log_access(method, canonical_path, 504)
        return JSONResponse({"error": "upstream timeout"}, status_code=504)
    except httpx.TimeoutException:
        _log_access(method, canonical_path, 504)
        return JSONResponse({"error": "upstream timeout"}, status_code=504)
    except httpx.TransportError:
        _log_access(method, canonical_path, 502)
        return JSONResponse({"error": "upstream transport error"}, status_code=502)

    # Forward the upstream response byte-faithfully (incl. a benign 404 on
    # /inference-profiles). Drop hop-by-hop + content-length/encoding so the
    # streamed body is re-framed correctly.
    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _DROP_HEADERS
        and k.lower() not in ("content-length", "content-encoding")
    }
    _log_access(method, canonical_path, upstream.status_code)
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=resp_headers,
        background=BackgroundTask(upstream.aclose),
    )
