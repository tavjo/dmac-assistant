"""Pydantic schemas for NExtSEEK entity tree vocab.

Ported from T2Viz src/schemas/entity_tree.py. The plugin-level
``EntityTree`` aggregate adds ``session_id`` + ``fetched_at`` for
on-disk caching (not in T2Viz).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NodeAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    node: str = Field(..., description="Sample type abbreviation, e.g. 'D.SEQ'")
    id: int = Field(..., description="Numeric sample type ID")
    description: str | None = Field(default=None)
    clade: str | None = Field(default=None)
    metadata_fields: str = Field(
        default="", description="Semicolon-delimited attribute titles"
    )


class EdgeAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    source: str
    target: str
    annotation: str
    internal_assay_id: str | None = Field(default=None)
    study_titles: str | None = Field(default=None)
    description: str | None = Field(default=None)


class NodeAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    total: int = Field(default=0)
    nodes: list[NodeAttribute] = Field(default_factory=list)


class EdgeAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    total: int = Field(default=0)
    edges: list[EdgeAttribute] = Field(default_factory=list)


class EntityTree(BaseModel):
    """Plugin-level assembled tree cached on disk."""

    session_id: str
    fetched_at: datetime
    nodes: list[NodeAttribute]
    edges: list[EdgeAttribute]
