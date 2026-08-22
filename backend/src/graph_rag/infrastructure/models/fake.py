"""In-memory / test doubles for model provider protocols."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from graph_rag.domain.elements.models import EquationVariable
from graph_rag.domain.graph.extraction import (
    EntityType,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedMeasurement,
    ExtractedRelationship,
    GraphExtractionResult,
)
from graph_rag.domain.graph.vocabulary import SemanticRelationshipType
from graph_rag.domain.models.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    ExtractionRequest,
    GenerationRequest,
    GenerationResponse,
    ModelCallMetadata,
    ModelRole,
    RerankRequest,
    RerankResponse,
    RerankResult,
    TokenCountRequest,
    TokenCountResponse,
    TokenUsage,
    VisionRequest,
    VisionResponse,
)
from graph_rag.domain.multimodal.schemas import (
    ChartEnrichmentResult,
    EquationEnrichmentResult,
    ImageEnrichmentResult,
    TableEnrichmentResult,
)

TModel = TypeVar("TModel", bound=BaseModel)

GenerationFn = Callable[[GenerationRequest], str]


class FakeChatModel:
    """Deterministic chat model for unit tests."""

    def __init__(
        self,
        text: str = "ok",
        *,
        response_fn: GenerationFn | None = None,
    ) -> None:
        self.text = text
        self.response_fn = response_fn
        self.calls: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls.append(request)
        text = self.response_fn(request) if self.response_fn is not None else self.text
        return GenerationResponse(
            text=text,
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-text",
                role=request.role,
                prompt_version=request.prompt_version,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
        )


class FakeVisionModel:
    """Deterministic vision model for unit tests."""

    def __init__(self, text: str = "visible chart with rising trend") -> None:
        self.text = text
        self.calls: list[VisionRequest] = []

    async def generate(self, request: VisionRequest) -> VisionResponse:
        self.calls.append(request)
        return VisionResponse(
            text=self.text,
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-vision",
                role=ModelRole.VISION,
                prompt_version=request.prompt_version,
                usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            ),
        )


class FakeStructuredExtractor:
    """Returns schema-appropriate enrichment payloads for tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[ExtractionRequest, type[BaseModel]]] = []

    async def extract(
        self,
        request: ExtractionRequest,
        output_schema: type[TModel],
    ) -> TModel:
        self.calls.append((request, output_schema))
        if output_schema is ImageEnrichmentResult:
            return output_schema(
                visual_summary="A labeled laboratory apparatus diagram",
                visible_labels_and_text=["Valve A", "Pump B"],
                objects_and_relationships=["valve connected to pump"],
                likely_purpose="Illustrate the process flow",
                supported_facts=["Valve A is upstream of Pump B"],
                uncertainty_notes=["Small annotations are partially blurred"],
            )
        if output_schema is ChartEnrichmentResult:
            return output_schema(
                chart_type="line",
                title="Viscosity vs Temperature",
                axes={"x": "temperature_C", "y": "viscosity_cP"},
                legend=["Sample A"],
                series=[{"name": "Sample A", "points": ["20C:12", "40C:8"]}],
                readable_values=["12 cP at 20C", "8 cP at 40C"],
                trends=["Viscosity decreases as temperature rises"],
                anomalies=[],
                supported_conclusions=["Inverse relationship between temperature and viscosity"],
                unreadable_regions=["Rightmost tick labels"],
                visual_summary="Line chart of viscosity falling with temperature",
            )
        if output_schema is TableEnrichmentResult:
            return output_schema(
                markdown="| Temp | Viscosity |\n| 20 | 12 |",
                structured_json={"rows": [{"temp": "20", "viscosity": "12"}]},
                semantic_summary="Table of temperature and viscosity measurements",
                row_observations=["First row records 20C / 12 cP"],
                column_observations=["Temperature and viscosity columns"],
                entity_links=["viscosity"],
            )
        if output_schema is EquationEnrichmentResult:
            return output_schema(
                latex="E=mc^2",
                variables=[
                    EquationVariable(name="E", definition="energy"),
                    EquationVariable(name="m", definition="mass"),
                    EquationVariable(name="c", definition="speed of light"),
                ],
                definition="Mass-energy equivalence",
                contextual_purpose="Relates energy to mass in the section",
                relationship_to_nearby_prose="Referenced by the preceding paragraph",
                semantic_description="Energy equals mass times the speed of light squared",
            )
        if output_schema is GraphExtractionResult:
            return output_schema(
                entities=[
                    ExtractedEntity(
                        name="Acme Viscosity Lab",
                        normalized_name="acme viscosity lab",
                        entity_type=EntityType.ORGANIZATION,
                        aliases=["AVL"],
                        confidence=0.93,
                    ),
                    ExtractedEntity(
                        name="AVL",
                        normalized_name="avl",
                        entity_type=EntityType.ORGANIZATION,
                        confidence=0.88,
                    ),
                    ExtractedEntity(
                        name="silicone oil",
                        normalized_name="silicone oil",
                        entity_type=EntityType.CHEMICAL,
                        confidence=0.9,
                    ),
                ],
                relationships=[
                    ExtractedRelationship(
                        source_entity="Acme Viscosity Lab",
                        target_entity="silicone oil",
                        predicate=SemanticRelationshipType.MEASURES,
                        confidence=0.8,
                    ),
                    ExtractedRelationship.model_validate(
                        {
                            "source_entity": "silicone oil",
                            "target_entity": "Acme Viscosity Lab",
                            "predicate": "studied_by_unknown",
                            "confidence": 0.55,
                        }
                    ),
                ],
                claims=[
                    ExtractedClaim(
                        statement="Viscosity decreases as temperature rises",
                        subject="silicone oil",
                        predicate="decreases_with",
                        object="temperature",
                        confidence=0.91,
                    )
                ],
                measurements=[
                    ExtractedMeasurement(
                        name="viscosity",
                        value="12",
                        unit="cP",
                        confidence=0.87,
                    )
                ],
                topics=["rheology", "temperature dependence"],
            )
        # Generic fallback for unexpected schemas.
        fields = {
            name: ("mock" if info.annotation is str else None)
            for name, info in output_schema.model_fields.items()
            if info.is_required()
        }
        return output_schema.model_validate(fields)


class FakeEmbeddingModel:
    """Deterministic embedding model for unit tests."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[self._vector(text) for text in request.texts],
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-embed",
                role=ModelRole.EMBEDDING,
            ),
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        folded = text.casefold()
        checksum = sum(ord(char) for char in folded) % 97
        length_signal = len(folded) % 53
        return [0.1 + checksum / 97.0, 0.2 + length_signal / 53.0]


class FakeReranker:
    """Lexical overlap reranker for unit tests."""

    def __init__(self) -> None:
        self.calls: list[RerankRequest] = []

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        self.calls.append(request)
        query_tokens = set(request.query.casefold().split())
        scored: list[tuple[int, str, float]] = []
        for index, item in enumerate(request.items):
            item_tokens = set(item.text.casefold().split())
            overlap = len(query_tokens & item_tokens)
            score = float(overlap) + (0.01 * (len(request.items) - index))
            scored.append((index, item.id, score))
        scored.sort(key=lambda row: row[2], reverse=True)
        top_n = request.top_n or len(scored)
        results = [
            RerankResult(id=item_id, score=score, index=index)
            for index, item_id, score in scored[:top_n]
        ]
        return RerankResponse(
            results=results,
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-rerank",
                role=ModelRole.RERANK,
            ),
        )


class FakeTokenCounter:
    """Character/4 token estimator used by enrichment tests."""

    async def count(self, request: TokenCountRequest) -> TokenCountResponse:
        return TokenCountResponse(
            token_count=max(1, (len(request.text) + 3) // 4) if request.text else 0,
            model_name=request.model_name or "fake-counter",
        )
