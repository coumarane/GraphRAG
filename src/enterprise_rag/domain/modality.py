"""Document and citation modality vocabulary."""

from __future__ import annotations

from enum import StrEnum


class Modality(StrEnum):
    """Evidence modality for chunks, citations and retrieval filters."""

    TEXT = "text"
    IMAGE = "image"
    CHART = "chart"
    DIAGRAM = "diagram"
    TABLE = "table"
    EQUATION = "equation"
    COMPOSITE = "composite"
