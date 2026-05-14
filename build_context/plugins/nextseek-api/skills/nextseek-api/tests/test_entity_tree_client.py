"""Tests for scripts/lib/entity_tree_client.py and scripts/lib/entity_tree_schemas.py."""
from __future__ import annotations

import httpx
import pytest
import respx

from lib.entity_tree_client import EntityTreeClient
from lib.entity_tree_schemas import (
    EdgeAttribute,
    EntityTree,
    NodeAttribute,
    NodeAttributeResponse,
)
from lib.nextseek_client import NextseekConfig


@pytest.fixture
def config() -> NextseekConfig:
    return NextseekConfig(
        base_url="https://nextseek.mit.edu/nextseek_api",
        username="u",
        password="p",
        timeout=5.0,
    )


def test_schemas_parse_fixture_payload() -> None:
    node = NodeAttribute.model_validate(
        {
            "node": "D.SEQ",
            "id": 1,
            "description": "DNA sequencing",
            "clade": "seq",
            "metadata_fields": "platform;depth",
        }
    )
    assert node.node == "D.SEQ"
    assert node.id == 1
    assert node.metadata_fields == "platform;depth"

    edge = EdgeAttribute.model_validate(
        {
            "source": "A",
            "target": "B",
            "annotation": "seq",
            "internal_assay_id": "IA-1",
            "study_titles": "",
            "description": "",
        }
    )
    assert edge.internal_assay_id == "IA-1"

    resp = NodeAttributeResponse.model_validate(
        {"total": 1, "nodes": [{"node": "X", "id": 9}]}
    )
    assert resp.total == 1
    assert resp.nodes[0].node == "X"


@respx.mock
def test_get_nodes_returns_parsed(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/nodes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "results": {
                    "total": 2,
                    "nodes": [
                        {
                            "node": "D.SEQ",
                            "id": 1,
                            "description": "DNA sequencing",
                            "clade": "seq",
                            "metadata_fields": "platform;depth",
                        },
                        {
                            "node": "RNA",
                            "id": 2,
                            "description": "RNA",
                            "clade": None,
                            "metadata_fields": "",
                        },
                    ],
                },
            },
        )
    )
    client = EntityTreeClient(config)
    nodes = client.get_nodes()
    assert nodes.total == 2
    assert len(nodes.nodes) == 2
    assert isinstance(nodes.nodes[0], NodeAttribute)
    assert nodes.nodes[0].node == "D.SEQ"


@respx.mock
def test_get_nodes_list_fallback(config: NextseekConfig) -> None:
    """Dev-server variation: results may be a plain list."""
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/nodes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": [
                    {"node": "A", "id": 1, "description": "a"},
                ],
            },
        )
    )
    nodes = EntityTreeClient(config).get_nodes()
    assert nodes.total == 1
    assert nodes.nodes[0].node == "A"


@respx.mock
def test_get_nodes_missing_results(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/nodes/"
    ).mock(return_value=httpx.Response(200, json={"count": 0, "next": None}))
    nodes = EntityTreeClient(config).get_nodes()
    assert nodes.total == 0
    assert nodes.nodes == []


@respx.mock
def test_get_edge_attributes_returns_parsed(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/edge_attributes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": {
                    "total": 1,
                    "edges": [
                        {
                            "source": "A",
                            "target": "B",
                            "annotation": "seq",
                            "internal_assay_id": "IA-1",
                            "study_titles": "",
                            "description": "",
                        }
                    ],
                },
            },
        )
    )
    edges = EntityTreeClient(config).get_edge_attributes()
    assert edges.total == 1
    assert edges.edges[0].internal_assay_id == "IA-1"


@respx.mock
def test_get_edge_attributes_list_fallback(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/edge_attributes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": [
                    {"source": "A", "target": "B", "annotation": "x"}
                ],
            },
        )
    )
    edges = EntityTreeClient(config).get_edge_attributes()
    assert edges.total == 1
    assert edges.edges[0].source == "A"


@respx.mock
def test_get_edge_attributes_missing_results(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/edge_attributes/"
    ).mock(return_value=httpx.Response(200, json={"count": 0, "next": None}))
    edges = EntityTreeClient(config).get_edge_attributes()
    assert edges.total == 0
    assert edges.edges == []


@respx.mock
def test_fetch_tree_assembles_nodes_and_edges(config: NextseekConfig) -> None:
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/nodes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": {
                    "total": 1,
                    "nodes": [{"node": "D.SEQ", "id": 1, "description": "x"}],
                },
            },
        )
    )
    respx.get(
        "https://nextseek.mit.edu/nextseek_api/entity_tree/edge_attributes/"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 0,
                "next": None,
                "results": {"total": 0, "edges": []},
            },
        )
    )
    tree = EntityTreeClient(config).fetch_tree(session_id="abc")
    assert isinstance(tree, EntityTree)
    assert tree.session_id == "abc"
    assert len(tree.nodes) == 1
    assert tree.nodes[0].node == "D.SEQ"
    assert tree.edges == []
    assert tree.fetched_at is not None
