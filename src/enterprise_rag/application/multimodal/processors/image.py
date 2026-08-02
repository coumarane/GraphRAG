"""Image and diagram enrichment processors."""

from __future__ import annotations

from enterprise_rag.application.multimodal.prompts import (
    build_extraction_request,
    context_as_prompt,
    element_text,
    provenance_from_call,
)
from enterprise_rag.domain.elements.context import ElementContext
from enterprise_rag.domain.elements.models import DiagramElement, DocumentElement, ImageElement
from enterprise_rag.domain.models.contracts import ModelCallMetadata, ModelRole, TokenUsage
from enterprise_rag.domain.models.protocols import StructuredExtractor
from enterprise_rag.domain.multimodal.schemas import ImageEnrichmentResult
from enterprise_rag.shared.exceptions import ValidationError

_PROMPT_VERSION = "image-enrichment-v1"
_SYSTEM = (
    "You analyze document images using surrounding context. "
    "Describe only what is visible. Do not invent unseen content."
)


class ImageProcessor:
    """Enrich image elements with vision/structured extraction."""

    name = "image_processor"

    def __init__(self, extractor: StructuredExtractor) -> None:
        self._extractor = extractor

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        if not isinstance(element, ImageElement):
            raise ValidationError(
                "ImageProcessor requires an ImageElement",
                details={"element_type": element.element_type.value},
            )
        result, call = await self._extract(element, context)
        ocr = " ".join(result.visible_labels_and_text).strip() or element.ocr_text
        return element.model_copy(
            update={
                "visual_description": result.visual_summary,
                "ocr_text": ocr,
                "model_provenance": provenance_from_call(call),
                "normalized_content": element.normalized_content
                or result.visual_summary,
            }
        )

    async def _extract(
        self,
        element: ImageElement | DiagramElement,
        context: ElementContext,
    ) -> tuple[ImageEnrichmentResult, ModelCallMetadata]:
        user = "\n".join(
            [
                context_as_prompt(context),
                f"element_id: {element.element_id}",
                f"asset_id: {element.source_asset_id}",
                f"raw_content: {element_text(element)}",
                "Return a structured image enrichment.",
            ]
        )
        request = build_extraction_request(
            system_prompt=_SYSTEM,
            user_text=user,
            prompt_version=_PROMPT_VERSION,
        )
        result = await self._extractor.extract(request, ImageEnrichmentResult)
        call = ModelCallMetadata(
            provider="structured_extractor",
            model_name="configured-extraction",
            role=ModelRole.EXTRACTION,
            prompt_version=_PROMPT_VERSION,
            usage=TokenUsage(),
            extras={"processor": self.name, "element_type": element.element_type.value},
        )
        if result.source_element_id is None:
            result = result.model_copy(update={"source_element_id": element.element_id})
        if result.source_asset_id is None and element.source_asset_id is not None:
            result = result.model_copy(update={"source_asset_id": element.source_asset_id})
        return result, call


class DiagramProcessor(ImageProcessor):
    """Enrich diagram elements using the same vision enrichment schema."""

    name = "diagram_processor"

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        if not isinstance(element, DiagramElement):
            raise ValidationError(
                "DiagramProcessor requires a DiagramElement",
                details={"element_type": element.element_type.value},
            )
        result, call = await self._extract(element, context)
        ocr = " ".join(result.visible_labels_and_text).strip() or element.ocr_text
        return element.model_copy(
            update={
                "visual_description": result.visual_summary,
                "ocr_text": ocr,
                "model_provenance": provenance_from_call(call),
                "normalized_content": element.normalized_content
                or result.visual_summary,
            }
        )
