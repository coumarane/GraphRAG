"""Table enrichment processor."""

from __future__ import annotations

from typing import cast

from graph_rag.application.multimodal.prompts import (
    build_extraction_request,
    context_as_prompt,
    element_text,
    provenance_from_call,
)
from graph_rag.domain.elements.context import ElementContext
from graph_rag.domain.elements.models import DocumentElement, TableElement
from graph_rag.domain.elements.table import TableData
from graph_rag.domain.models.contracts import ModelCallMetadata, ModelRole, TokenUsage
from graph_rag.domain.models.protocols import StructuredExtractor
from graph_rag.domain.multimodal.schemas import TableEnrichmentResult
from graph_rag.domain.types import JsonValue
from graph_rag.shared.exceptions import ValidationError

_PROMPT_VERSION = "table-enrichment-v1"
_SYSTEM = (
    "You enrich document tables. Preserve existing cell structure. "
    "Add semantic summary and observations without inventing cells."
)


class TableProcessor:
    """Enrich tables while preserving original parsed structure."""

    name = "table_processor"

    def __init__(self, extractor: StructuredExtractor) -> None:
        self._extractor = extractor

    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> DocumentElement:
        if not isinstance(element, TableElement):
            raise ValidationError(
                "TableProcessor requires a TableElement",
                details={"element_type": element.element_type.value},
            )
        user = "\n".join(
            [
                context_as_prompt(context),
                f"element_id: {element.element_id}",
                f"caption: {element.table.caption or context.caption or ''}",
                f"markdown: {element.table.markdown or element_text(element)}",
                f"headers: {element.table.column_headers}",
                "Return table enrichment. Do not invent missing cell values.",
            ]
        )
        request = build_extraction_request(
            system_prompt=_SYSTEM,
            user_text=user,
            prompt_version=_PROMPT_VERSION,
        )
        result = await self._extractor.extract(request, TableEnrichmentResult)
        call = ModelCallMetadata(
            provider="structured_extractor",
            model_name="configured-extraction",
            role=ModelRole.EXTRACTION,
            prompt_version=_PROMPT_VERSION,
            usage=TokenUsage(),
            extras={"processor": self.name},
        )
        # Preserve original cells/headers; only fill summary/markdown gaps.
        table = TableData(
            caption=element.table.caption,
            column_headers=list(element.table.column_headers),
            row_headers=list(element.table.row_headers),
            cells=list(element.table.cells),
            footnotes=list(element.table.footnotes),
            raw_parser_representation=element.table.raw_parser_representation,
            markdown=element.table.markdown or result.markdown,
            semantic_summary=result.semantic_summary,
        )
        metadata: dict[str, JsonValue] = {
            **element.metadata,
            "row_observations": cast(JsonValue, list(result.row_observations)),
            "column_observations": cast(JsonValue, list(result.column_observations)),
            "entity_links": cast(JsonValue, list(result.entity_links)),
            "structured_json": result.structured_json,
            "model_provenance": provenance_from_call(call),
        }
        return element.model_copy(
            update={
                "table": table,
                "metadata": metadata,
                "normalized_content": element.normalized_content
                or result.semantic_summary
                or element.table.markdown,
            }
        )
