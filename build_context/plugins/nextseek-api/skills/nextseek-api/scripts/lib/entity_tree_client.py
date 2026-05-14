"""Sync NExtSEEK entity tree client.

Ported from T2Viz async client. Fetches `/entity_tree/nodes/` and
`/entity_tree/edge_attributes/` sequentially and assembles them into a
plugin-level ``EntityTree`` carrying ``session_id`` + ``fetched_at`` for
on-disk caching (see DD-10). The `/entity_tree/edges/` endpoint is
intentionally skipped — edge_attributes is a superset.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from lib.entity_tree_schemas import (
    EdgeAttribute,
    EdgeAttributeResponse,
    EntityTree,
    NodeAttribute,
    NodeAttributeResponse,
)
from lib.env_loader import canonicalize_endpoint
from lib.nextseek_client import NextseekConfig


class EntityTreeClient:
    NODES_PATH = "entity_tree/nodes/"
    EDGE_ATTR_PATH = "entity_tree/edge_attributes/"

    def __init__(self, config: NextseekConfig) -> None:
        self._config = config

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._config.base_url.rstrip("/") + "/",
            auth=httpx.BasicAuth(self._config.username, self._config.password),
            timeout=self._config.timeout,
        )

    def _get(self, path: str) -> dict:
        with self._client() as c:
            r = c.get(canonicalize_endpoint(path))
            r.raise_for_status()
            return r.json()

    def get_nodes(self) -> NodeAttributeResponse:
        data = self._get(self.NODES_PATH)
        results = data.get("results")
        if isinstance(results, dict):
            return NodeAttributeResponse.model_validate(results)
        if isinstance(results, list):
            return NodeAttributeResponse(
                total=data.get("count", len(results)),
                nodes=[NodeAttribute.model_validate(r) for r in results],
            )
        return NodeAttributeResponse(total=0, nodes=[])

    def get_edge_attributes(self) -> EdgeAttributeResponse:
        data = self._get(self.EDGE_ATTR_PATH)
        results = data.get("results")
        if isinstance(results, dict):
            return EdgeAttributeResponse.model_validate(results)
        if isinstance(results, list):
            return EdgeAttributeResponse(
                total=data.get("count", len(results)),
                edges=[EdgeAttribute.model_validate(r) for r in results],
            )
        return EdgeAttributeResponse(total=0, edges=[])

    def fetch_tree(self, session_id: str) -> EntityTree:
        nodes_resp = self.get_nodes()
        edges_resp = self.get_edge_attributes()
        return EntityTree(
            session_id=session_id,
            fetched_at=datetime.now(timezone.utc),
            nodes=nodes_resp.nodes,
            edges=edges_resp.edges,
        )
