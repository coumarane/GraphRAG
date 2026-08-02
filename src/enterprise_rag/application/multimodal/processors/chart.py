"""Chart enrichment processor."""

from __future__ import annotations

from typing import cast

from enterprise_rag.application.multimodal.prompts import (
    build_extraction_request,
    context_as_prompt,
    element_text,
    provenance_from_call,
)
from enterprise_rag.domain.elements.context import ElementContext
from enterprise_rag.domain.elements.models import ChartElement, DocumentElement
from enterprise_rag.domain.models.contracts import ModelCallMetadata, ModelRole, TokenUsage
from enterprise_rag.domain.models.protocols import StructuredExtractor
from enterprise_rag.domain.multimodal.schemas import ChartEnrichmentResult
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.shared.exceptions import ValidationError

_PROMPT_VERSION = "chart-enrichment-v1"
_SYSTEM = (
    "You analyze charts in documents. Never invent numeric values that are not "
    "clearly readable. Mark ambiguous regions explicitly."
)


class ChartProcessor:
    """Enrich chart elements without fabricating unread values."""

    name = "chart_processor"

    def __init__(self, extractor: StructuredExtractor) -> None:
        self._extractor = extractor

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        if not isinstance(element, ChartElement):
            raise ValidationError(
                "ChartProcessor requires a ChartElement",
                details={"element_type": element.element_type.value},
            )
        user = "\n".join(
            [
                context_as_prompt(context),
                f"element_id: {element.element_id}",
                f"existing_chart_type: {element.chart_type or ''}",
                f"existing_title: {element.title or ''}",
                f"raw_content: {element_text(element)}",
                "Return structured chart enrichment. Do not invent unread values.",
            ]
        )
        request = build_extraction_request(
            system_prompt=_SYSTEM,
            user_text=user,
            prompt_version=_PROMPT_VERSION,
        )
        result = await self._extractor.extract(request, ChartEnrichmentResult)
        call = ModelCallMetadata(
            provider="structured_extractor",
            model_name="configured-extraction",
            role=ModelRole.EXTRACTION,
            prompt_version=_PROMPT_VERSION,
            usage=TokenUsage(),
            extras={"processor": self.name},
        )
        return element.model_copy(
            update={
                "chart_type": result.chart_type or element.chart_type,
                "title": result.title or element.title,
                "axes": result.axes or element.axes,
                "legend": result.legend or element.legend,
                "series": result.series or element.series,
                "trends": result.trends or element.trends,
                "anomalies": result.anomalies or element.anomalies,
                "visual_description": result.visual_summary or element.visual_description,
                "model_provenance": provenance_from_call(call),
                "normalized_content": element.normalized_content
                or result.visual_summary
                or element.title,
                "metadata": {
                    **element.metadata,
                    "readable_values": cast(JsonValue, list(result.readable_values)),
                    "supported_conclusions": cast(
                        JsonValue, list(result.supported_conclusions)
                    ),
                    "unreadable_regions": cast(JsonValue, list(result.unreadable_regions)),
                },
            }
        )
