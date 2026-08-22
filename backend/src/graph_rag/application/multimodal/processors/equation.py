"""Equation enrichment processor."""

from __future__ import annotations

from graph_rag.application.multimodal.prompts import (
    build_extraction_request,
    context_as_prompt,
    element_text,
    provenance_from_call,
)
from graph_rag.domain.elements.context import ElementContext
from graph_rag.domain.elements.models import DocumentElement, EquationElement
from graph_rag.domain.models.contracts import ModelCallMetadata, ModelRole, TokenUsage
from graph_rag.domain.models.protocols import StructuredExtractor
from graph_rag.domain.multimodal.schemas import EquationEnrichmentResult
from graph_rag.shared.exceptions import ValidationError

_PROMPT_VERSION = "equation-enrichment-v1"
_SYSTEM = (
    "You enrich mathematical equations with contextual meaning. "
    "Do not solve the equation. Prefer existing LaTeX/MathML when present."
)


class EquationProcessor:
    """Enrich equations with variables and searchable semantics."""

    name = "equation_processor"

    def __init__(self, extractor: StructuredExtractor) -> None:
        self._extractor = extractor

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        if not isinstance(element, EquationElement):
            raise ValidationError(
                "EquationProcessor requires an EquationElement",
                details={"element_type": element.element_type.value},
            )
        user = "\n".join(
            [
                context_as_prompt(context),
                f"element_id: {element.element_id}",
                f"latex: {element.latex or ''}",
                f"mathml: {element.mathml or ''}",
                f"raw_content: {element_text(element)}",
                "Return equation enrichment. Do not solve the equation.",
            ]
        )
        request = build_extraction_request(
            system_prompt=_SYSTEM,
            user_text=user,
            prompt_version=_PROMPT_VERSION,
        )
        result = await self._extractor.extract(request, EquationEnrichmentResult)
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
                "latex": element.latex or result.latex,
                "mathml": element.mathml or result.mathml,
                "variables": result.variables or element.variables,
                "contextual_explanation": result.contextual_purpose
                or result.definition
                or element.contextual_explanation,
                "semantic_description": result.semantic_description,
                "model_provenance": provenance_from_call(call),
                "normalized_content": element.normalized_content
                or result.semantic_description
                or element.latex,
                "metadata": {
                    **element.metadata,
                    "relationship_to_nearby_prose": result.relationship_to_nearby_prose,
                },
            }
        )
