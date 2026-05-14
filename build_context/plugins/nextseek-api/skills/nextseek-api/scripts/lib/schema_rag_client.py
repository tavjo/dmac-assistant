"""Sync SchemaRAG client with persistent disk-based session cache.

Ported from T2Viz async SchemaRAGClient. Key differences:
  - Sync (no async/await) — calls self._http_client.post() directly.
  - Persistent disk cache at ~/.cache/nextseek-api/{env_tag}/session.json.
  - Env-scoped cache dirs (dev vs prod) to prevent session cross-contamination.
  - Auto-reingest on expiry OR 401, bounded to ONE retry to avoid infinite loops.
  - On-disk session.json shape matches the SessionState pydantic model
    (session_id, expires_at, base_url, env_tag, schema_url) — CL-4.
  - Context-manager compatible; caller owns the NextseekClient lifecycle — CL-3.
  - Honors XDG_CACHE_HOME via lib.cache_paths — CL-7.

References:
  - T2Viz src/clients/schema_rag_client.py (async source)
  - dmac-curation-tools src/dmac_curation/api/schema_rag.py (sync variant,
    in-memory cache; this client swaps in-memory for disk persistence).
  - CONTRACT_LOCK CL-3/CL-4/CL-7 for the locked public API surface.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lib.cache_paths import resolve_plugin_cache_base
from lib.models import (
    FullEndpoint,
    IngestResponse,
    MinimalEndpoint,
    SchemaRAGResponse,
    SessionState,
)
from lib.nextseek_client import NextseekAuthError, NextseekClient, SessionExpiredError

logger = logging.getLogger(__name__)


class SchemaRAGClient:
    """Synchronous NExtSEEK Schema RAG client with disk-persistent sessions.

    Usage (CL-3 locked API)::

        from lib.cache_paths import resolve_plugin_cache_base

        with NextseekClient(config=config) as http_client:
            with SchemaRAGClient(
                http_client,
                env_tag="dev",
                base_url=config.base_url,
                cache_base_dir=resolve_plugin_cache_base(),
            ) as rag:
                resp: SchemaRAGResponse = rag.retrieve_with_auto_ingest(
                    "all endpoints", mode="minimal", top_k="ALL"
                )
                endpoints = [ep.model_dump(by_alias=False) for ep in resp.endpoints]
                state = rag.current_session_state()
    """

    INGEST_ENDPOINT = "schema_rag/ingest/"
    RETRIEVE_ENDPOINT = "schema_rag/retrieve/"
    DEFAULT_SCHEMA_URL = "https://nextseek-dev.mit.edu/nextseek_api/schema/?format=yaml"
    DEFAULT_TTL_MINUTES = 30

    def __init__(
        self,
        http_client: NextseekClient,
        *,
        env_tag: Literal["dev", "prod"],
        base_url: str,
        default_schema_url: str | None = None,
        cache_base_dir: Path | None = None,
    ) -> None:
        """Construct a SchemaRAGClient.

        Args (CL-3):
            http_client: An already-entered NextseekClient. The caller owns
                the http_client lifecycle; SchemaRAGClient never calls
                __enter__/__exit__ on it.
            env_tag: "dev" or "prod". Used for cache scoping AND written to
                session.json as SessionState.env_tag.
            base_url: The base URL used by the http_client. Stored in
                SessionState for later retrieval via current_session_state().
                Required per CL-4.
            default_schema_url: Optional override for the schema URL used in
                ingest. Defaults to the NExtSEEK dev schema URL.
            cache_base_dir: Base cache directory WITHOUT the env suffix. If
                None, uses resolve_plugin_cache_base() from lib.cache_paths
                (which honors XDG_CACHE_HOME). The client always appends
                /{env_tag} internally.
        """
        if env_tag not in ("dev", "prod"):
            raise ValueError(f"env_tag must be 'dev' or 'prod', got {env_tag!r}")
        self._http_client = http_client
        self._env_tag = env_tag
        self._base_url = base_url
        self._default_schema_url = default_schema_url or self.DEFAULT_SCHEMA_URL

        # CL-7: cache path resolution. Default uses lib.cache_paths helper
        # (which honors XDG_CACHE_HOME); explicit cache_base_dir wins for
        # tests and lets them pass isolated tmp_path roots.
        base = Path(cache_base_dir) if cache_base_dir else resolve_plugin_cache_base()
        self._cache_dir = base / env_tag
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session_path = self._cache_dir / "session.json"

    # ------------------------------------------------------------------
    # Context-manager protocol (CL-3)
    # ------------------------------------------------------------------

    def __enter__(self) -> "SchemaRAGClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # No-op. The caller owns the underlying NextseekClient lifecycle.
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        schema_url: str | None = None,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> IngestResponse:
        """Ingest an OpenAPI schema and persist the session to disk.

        On success, session.json is written in the CL-4 SessionState shape.
        """
        url = schema_url or self._default_schema_url
        payload = {"schema_url": url, "ttl_minutes": ttl_minutes}
        raw = self._http_client.post(self.INGEST_ENDPOINT, json=payload)
        response = IngestResponse.model_validate(raw)

        self._write_session(
            session_id=response.session_id,
            expires_at=response.expires_at,
            schema_url=url,
        )
        logger.info(
            "schema_rag_ingested",
            extra={
                "session_id": response.session_id,
                "num_endpoints": response.num_endpoints,
                "env_tag": self._env_tag,
            },
        )
        return response

    def retrieve(
        self,
        query: str,
        *,
        mode: Literal["minimal", "full"] = "full",
        top_k: int | str = 5,
        min_score: float = 0.0,
        filter_by: str | None = None,
        filter_terms: list[str] | None = None,
        session_id: str | None = None,
        schema_url: str | None = None,
    ) -> SchemaRAGResponse:
        """Retrieve relevant endpoints for a natural-language query.

        This is a thin wrapper over POST /schema_rag/retrieve/. It does NOT
        auto-reingest on its own — call retrieve_with_auto_ingest() for that.
        """
        # DD-15 (task-02 / issue #17): surface expired sessions as a typed
        # error BEFORE any HTTP traffic. Only fires when no explicit
        # session_id was passed AND a cached session file exists but is past
        # its TTL — a fresh install (no session.json yet) is left to the
        # pre-existing auto-ingest path in retrieve_with_auto_ingest().
        if session_id is None:
            cached_state = self.current_session_state()
            if cached_state is not None:
                expires_at = cached_state.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= expires_at:
                    raise SessionExpiredError()

        sid = session_id or self._load_cached_session_id()

        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "mode": mode,
        }
        if sid:
            payload["session_id"] = sid
        if schema_url:
            payload["schema_url"] = schema_url
        if filter_by:
            payload["filter_by"] = filter_by
        if filter_terms:
            payload["filter_terms"] = filter_terms

        raw = self._http_client.post(self.RETRIEVE_ENDPOINT, json=payload)

        if mode == "full":
            endpoint_cls: type[MinimalEndpoint] = FullEndpoint
            raw_endpoints = raw.get("endpoints_full") or []
        else:
            endpoint_cls = MinimalEndpoint
            raw_endpoints = raw.get("endpoints_minimal") or []
        endpoints = [endpoint_cls.model_validate(ep) for ep in raw_endpoints]

        response = SchemaRAGResponse(
            query=query,
            endpoints=endpoints,
            total_results=len(endpoints),
            session_id=raw.get("session_id"),
            mode=raw.get("mode", mode),
        )
        logger.info(
            "schema_rag_retrieved",
            extra={"query": query[:80], "total": response.total_results, "mode": mode},
        )
        return response

    def retrieve_with_auto_ingest(
        self,
        query: str,
        *,
        schema_url: str | None = None,
        **kwargs: Any,
    ) -> SchemaRAGResponse:
        """Retrieve with silent auto-reingest on expiry or 401.

        Bounded to ONE reingest+retry. If the reingest itself fails OR if
        the retry also fails, the original NextseekAuthError propagates.
        Matches DD-06 and CL-3.
        """
        url = schema_url or self._default_schema_url

        # Pre-check: is the cached session expired or missing?
        if self._load_cached_session_id() is None:
            self.ingest(schema_url=url)

        try:
            return self.retrieve(query, schema_url=schema_url, **kwargs)
        except (NextseekAuthError, SessionExpiredError) as original_err:
            logger.info(
                "schema_rag_reingest_on_401",
                extra={"env_tag": self._env_tag, "query": query[:80]},
            )
            # One-shot retry: reingest, then retry retrieve exactly once.
            # If the reingest itself fails, re-raise the ORIGINAL error so
            # the caller sees the first cause of the failure (no infinite
            # loop). SessionExpiredError is treated the same as a 401 here:
            # the pre-check normally catches expiry, but if a session ticks
            # past its TTL between the pre-check and the retrieve call, the
            # auto-reingest flow still rescues it.
            try:
                self.ingest(schema_url=url)
            except NextseekAuthError:
                raise original_err
            return self.retrieve(query, schema_url=schema_url, **kwargs)

    def retrieve_full(self, operation_id: str) -> FullEndpoint:
        """Retrieve the full spec for an exact operation_id.

        Calls ``retrieve_with_auto_ingest(query=operation_id, mode="full", top_k=1)``
        and asserts the top hit's ``operation_id`` matches. Raises ``LookupError``
        on mismatch (unknown op_id) so callers can distinguish "no such op" from
        network errors.
        """
        resp = self.retrieve_with_auto_ingest(operation_id, mode="full", top_k=1)
        for ep in resp.endpoints:
            if isinstance(ep, FullEndpoint) and ep.operation_id == operation_id:
                return ep
        raise LookupError(f"no endpoint with operation_id={operation_id!r}")

    def retrieve_full_by_query(
        self, query: str, *, top_k: int = 1
    ) -> FullEndpoint:
        """Retrieve top-scoring full endpoint for a natural-language query.

        Raises ``LookupError`` if zero hits. Ambiguity (>1 hit) is resolved at
        a higher layer, not here.
        """
        resp = self.retrieve_with_auto_ingest(query, mode="full", top_k=top_k)
        if not resp.endpoints:
            raise LookupError(f"no endpoint matches query={query!r}")
        ep = resp.endpoints[0]
        if not isinstance(ep, FullEndpoint):
            raise LookupError(
                f"top hit for query={query!r} was not a FullEndpoint"
            )
        return ep

    def current_session_state(self) -> SessionState | None:
        """Return the on-disk SessionState, or None if missing/unparseable.

        Reads {cache_dir}/session.json and validates it against the
        SessionState pydantic model. Round-trip of CL-4 shape.
        """
        if not self._session_path.exists():
            return None
        try:
            raw = json.loads(self._session_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "schema_rag_session_cache_unreadable",
                extra={"env_tag": self._env_tag},
            )
            return None
        try:
            return SessionState.model_validate(raw)
        except Exception:
            logger.warning(
                "schema_rag_session_state_invalid",
                extra={"env_tag": self._env_tag},
            )
            return None

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _session_json_path(self) -> Path:
        """Internal: path to session.json for this env_tag."""
        return self._session_path

    def _write_session(
        self,
        session_id: str,
        expires_at: datetime,
        schema_url: str | None = None,
    ) -> None:
        """Write session state to disk in the CL-4 SessionState shape.

        Fields (exact): session_id, expires_at (ISO-8601), base_url,
        env_tag, schema_url. No extra fields. Must round-trip through
        SessionState.model_validate(json.loads(path.read_text())).
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        data = {
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
            "base_url": self._base_url,
            "env_tag": self._env_tag,
            "schema_url": schema_url or self._default_schema_url,
        }
        self._session_path.write_text(json.dumps(data, indent=2))

    def _load_cached_session(self) -> SessionState | None:
        """Internal alias for current_session_state()."""
        return self.current_session_state()

    def _load_cached_session_id(self) -> str | None:
        """Return the cached session_id if present and not expired, else None.

        Uses current_session_state() for parsing and then checks expiry.
        """
        state = self.current_session_state()
        if state is None:
            return None
        expires_at = state.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return state.session_id

    def clear_session_cache(self) -> None:
        """Delete the persisted session file (idempotent)."""
        try:
            self._session_path.unlink()
        except FileNotFoundError:
            pass
