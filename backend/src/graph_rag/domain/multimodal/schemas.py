"""Structured enrichment outputs for multimodal processors."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.elements.models import EquationVariable
from graph_rag.domain.types import JsonValue


class ImageEnrichmentResult(BaseModel):
    """Vision enrichment for image/diagram elements."""

    model_config = ConfigDict(extra="forbid")

    visual_summary: str
    visible_labels_and_text: list[str] = Field(default_factory=list)
    objects_and_relationships: list[str] = Field(default_factory=list)
    likely_purpose: str | None = None
    supported_facts: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    source_element_id: UUID | None = None
    source_asset_id: UUID | None = None


class ChartEnrichmentResult(BaseModel):
    """Structured chart understanding. Never invent unread values."""

    model_config = ConfigDict(extra="forbid")

    chart_type: str | None = None
    title: str | None = None
    axes: dict[str, JsonValue] = Field(default_factory=dict)
    legend: list[str] = Field(default_factory=list)
    series: list[dict[str, JsonValue]] = Field(default_factory=list)
    readable_values: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    supported_conclusions: list[str] = Field(default_factory=list)
    unreadable_regions: list[str] = Field(default_factory=list)
    visual_summary: str | None = None
    source_element_id: UUID | None = None
    source_asset_id: UUID | None = None


class TableEnrichmentResult(BaseModel):
    """Table semantic enrichment preserving original structure."""

    model_config = ConfigDict(extra="forbid")

    markdown: str | None = None
    structured_json: dict[str, JsonValue] = Field(default_factory=dict)
    semantic_summary: str
    row_observations: list[str] = Field(default_factory=list)
    column_observations: list[str] = Field(default_factory=list)
    entity_links: list[str] = Field(default_factory=list)
    source_element_id: UUID | None = None


class EquationEnrichmentResult(BaseModel):
    """Equation contextual enrichment. Does not solve the equation."""

    model_config = ConfigDict(extra="forbid")

    latex: str | None = None
    mathml: str | None = None
    variables: list[EquationVariable] = Field(default_factory=list)
    definition: str | None = None
    contextual_purpose: str | None = None
    relationship_to_nearby_prose: str | None = None
    semantic_description: str
    source_element_id: UUID | None = None
