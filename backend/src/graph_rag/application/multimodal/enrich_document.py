"""Orchestrate context-aware multimodal document enrichment."""

from __future__ import annotations

from dataclasses import dataclass, field

from graph_rag.application.multimodal.processors import (
    ChartProcessor,
    DiagramProcessor,
    EquationProcessor,
    ImageProcessor,
    TableProcessor,
)
from graph_rag.config.settings import MultimodalSettings
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.models import DocumentElement
from graph_rag.domain.models.protocols import StructuredExtractor, TokenCounter
from graph_rag.domain.multimodal.context_builder import (
    ContextBuilderConfig,
    ElementContextBuilder,
)
from graph_rag.domain.multimodal.protocols import MultimodalElementProcessor
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EnrichmentResult:
    """Outcome of enriching a normalized document."""

    document: NormalizedDocument
    enriched_element_ids: list[str] = field(default_factory=list)
    skipped_element_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class EnrichDocumentService:
    """Enrich images, charts, tables and equations with local context."""

    def __init__(
        self,
        extractor: StructuredExtractor,
        *,
        settings: MultimodalSettings | None = None,
        token_counter: TokenCounter | None = None,
        processors: dict[ElementType, MultimodalElementProcessor] | None = None,
    ) -> None:
        self._settings = settings or MultimodalSettings()
        self._builder = ElementContextBuilder(
            config=ContextBuilderConfig(
                preceding_elements=self._settings.context_before_elements,
                following_elements=self._settings.context_after_elements,
                max_context_tokens=self._settings.maximum_context_tokens,
            ),
            token_counter=token_counter,
        )
        self._processors = processors or {
            ElementType.IMAGE: ImageProcessor(extractor),
            ElementType.DIAGRAM: DiagramProcessor(extractor),
            ElementType.CHART: ChartProcessor(extractor),
            ElementType.TABLE: TableProcessor(extractor),
            ElementType.EQUATION: EquationProcessor(extractor),
        }

    async def enrich(self, document: NormalizedDocument) -> EnrichmentResult:
        if not self._settings.enabled:
            return EnrichmentResult(document=document, warnings=["multimodal enrichment disabled"])

        enriched_ids: list[str] = []
        skipped_ids: list[str] = []
        warnings: list[str] = []
        updated: list[DocumentElement] = []

        for element in document.elements:
            processor = self._processors.get(element.element_type)
            if processor is None or not self._is_enabled(element.element_type):
                updated.append(element)
                if element.element_type in self._processors:
                    skipped_ids.append(str(element.element_id))
                continue
            try:
                context = await self._builder.build(document, element)
                enriched = await processor.process(element, context)
                # Guarantees: original identity and raw parse content preserved.
                if enriched.element_id != element.element_id:
                    raise RuntimeError("processor changed element_id")
                if element.raw_content is not None and enriched.raw_content != element.raw_content:
                    enriched = enriched.model_copy(update={"raw_content": element.raw_content})
                updated.append(enriched)
                enriched_ids.append(str(element.element_id))
            except Exception as exc:
                warnings.append(f"{element.element_type.value}:{element.element_id}: {exc}")
                logger.warning(
                    "multimodal_enrichment_failed",
                    element_id=str(element.element_id),
                    element_type=element.element_type.value,
                    error=str(exc),
                )
                updated.append(element)
                skipped_ids.append(str(element.element_id))

        return EnrichmentResult(
            document=document.model_copy(update={"elements": updated}),
            enriched_element_ids=enriched_ids,
            skipped_element_ids=skipped_ids,
            warnings=warnings,
        )

    def _is_enabled(self, element_type: ElementType) -> bool:
        if element_type is ElementType.IMAGE or element_type is ElementType.DIAGRAM:
            return self._settings.process_images
        if element_type is ElementType.CHART:
            return self._settings.process_charts
        if element_type is ElementType.TABLE:
            return self._settings.process_tables
        if element_type is ElementType.EQUATION:
            return self._settings.process_equations
        return False
