"""Multimodal enrichment processor protocols."""

from __future__ import annotations

from typing import Protocol

from enterprise_rag.domain.elements.context import ElementContext
from enterprise_rag.domain.elements.models import DocumentElement


class MultimodalElementProcessor(Protocol):
    """Enrich a single multimodal element using local document context."""

    @property
    def name(self) -> str:
        """Stable processor name for provenance."""
        ...

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        """Return an enriched copy; never mutate the original element in place."""
        ...
