"""Geometry types for layout-aware elements."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.types import JsonValue


class BoundingBox(BaseModel):
    """Axis-aligned region in normalized page coordinates (0..1).

    Original parser coordinates may be preserved under ``metadata``.
    """

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
