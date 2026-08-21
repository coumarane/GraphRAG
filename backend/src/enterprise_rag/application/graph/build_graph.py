"""Compose structural + semantic graph and project to a graph store."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from enterprise_rag.application.graph.extract import ExtractGraphFromChunksService
from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.graph.extraction import GraphExtractionResult
from enterprise_rag.domain.graph.models import (
    EntityResolutionDecision,
    GraphNode,
    GraphRelationship,
    ProjectedGraph,
    ResolvedEntity,
)
from enterprise_rag.domain.graph.protocols import GraphStore
from enterprise_rag.domain.graph.resolution import EntityResolver
from enterprise_rag.domain.graph.structural import StructuralGraphBuilder
from enterprise_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralRelationshipType,
)
from enterprise_rag.domain.ids import deterministic_id
from enterprise_rag.domain.models.protocols import StructuredExtractor
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.types import JsonValue


@dataclass
class KnowledgeGraphBuildResult:
    """Outcome of structural + semantic graph construction."""

    graph: ProjectedGraph
    entities: list[ResolvedEntity] = field(default_factory=list)
    decisions: list[EntityResolutionDecision] = field(default_factory=list)
    extractions: list[GraphExtractionResult] = field(default_factory=list)
    upsert_counts: dict[str, int] = field(default_factory=dict)


class BuildKnowledgeGraphService:
    """Extract, resolve, merge structural/semantic graphs, and upsert."""

    def __init__(
        self,
        extractor: StructuredExtractor,
        graph_store: GraphStore,
        *,
        structural_builder: StructuralGraphBuilder | None = None,
    ) -> None:
        self._extract = ExtractGraphFromChunksService(extractor)
        self._store = graph_store
        self._structural = structural_builder or StructuralGraphBuilder()

    async def build(
        self,
        tenant: TenantContext,
        document: NormalizedDocument,
        chunks: ChunkingResult | list[ChunkBase],
        *,
        persist: bool = True,
    ) -> KnowledgeGraphBuildResult:
        chunking = (
            chunks
            if isinstance(chunks, ChunkingResult)
            else ChunkingResult(
                parents=[c for c in chunks if c.parent_chunk_id is None],
                children=[c for c in chunks if c.parent_chunk_id is not None],
            )
        )
        structural = self._structural.build(document, chunking)
        extractable = [
            *chunking.parents,
            *[
                child
                for child in chunking.children
                if child.chunk_type.value in {"multimodal_composite", "table"}
            ],
        ]
        extracted_pairs = []
        for chunk in extractable:
            extracted_pairs.append((chunk, await self._extract.extract_chunk(chunk)))

        resolver = EntityResolver(tenant_id=tenant.tenant_id)
        all_extractions = [result for _, result in extracted_pairs]
        for _, extraction in extracted_pairs:
            resolver.resolve_many(extraction.entities)
        entities, decisions = list(resolver.entities.values()), list(resolver.decisions)

        semantic = self._semantic_projection(
            tenant_id=tenant.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            entities=entities,
            pairs=extracted_pairs,
            entity_index={
                entity.normalized_name: entity for entity in entities
            },
        )

        merged = ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            nodes=[*structural.nodes, *semantic.nodes],
            relationships=[*structural.relationships, *semantic.relationships],
        )
        counts: dict[str, int] = {}
        if persist:
            counts = await self._store.upsert_graph(tenant, merged)
        return KnowledgeGraphBuildResult(
            graph=merged,
            entities=entities,
            decisions=decisions,
            extractions=all_extractions,
            upsert_counts=counts,
        )

    def _semantic_projection(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        version_id: UUID,
        entities: list[ResolvedEntity],
        pairs: list[tuple[ChunkBase, GraphExtractionResult]],
        entity_index: dict[str, ResolvedEntity],
    ) -> ProjectedGraph:
        from enterprise_rag.domain.graph.resolution import normalize_entity_name

        nodes: list[GraphNode] = []
        relationships: list[GraphRelationship] = []

        for entity in entities:
            nodes.append(
                GraphNode(
                    node_id=entity.entity_id,
                    label=entity.entity_type,
                    tenant_id=tenant_id,
                    properties={
                        "entity_id": str(entity.entity_id),
                        "canonical_name": entity.canonical_name,
                        "normalized_name": entity.normalized_name,
                        "aliases": list(entity.aliases),
                        "description": entity.description,
                        # Shared across documents — do not stamp version ownership.
                        "mention_count": entity.mention_count,
                    },
                )
            )

        for chunk, extraction in pairs:
            for topic in extraction.topics:
                topic_id = deterministic_id(str(tenant_id), "topic", normalize_entity_name(topic))
                nodes.append(
                    GraphNode(
                        node_id=topic_id,
                        label=SemanticNodeLabel.TOPIC.value,
                        tenant_id=tenant_id,
                        properties={"name": topic, "normalized_name": normalize_entity_name(topic)},
                    )
                )
                relationships.append(
                    GraphRelationship(
                        relationship_id=deterministic_id(
                            str(tenant_id), "MENTIONS", str(chunk.chunk_id), str(topic_id)
                        ),
                        relationship_type=SemanticRelationshipType.MENTIONS.value,
                        tenant_id=tenant_id,
                        source_node_id=chunk.chunk_id,
                        target_node_id=topic_id,
                        properties={"via": "topic"},
                    )
                )

            for claim in extraction.claims:
                claim_id = deterministic_id(
                    str(tenant_id),
                    "claim",
                    str(chunk.chunk_id),
                    claim.statement[:80],
                )
                nodes.append(
                    GraphNode(
                        node_id=claim_id,
                        label=SemanticNodeLabel.CLAIM.value,
                        tenant_id=tenant_id,
                        properties={
                            "statement": claim.statement,
                            "subject": claim.subject,
                            "predicate": claim.predicate,
                            "object": claim.object,
                            "confidence": claim.confidence,
                        },
                    )
                )
                relationships.append(
                    GraphRelationship(
                        relationship_id=deterministic_id(
                            str(tenant_id),
                            StructuralRelationshipType.DERIVED_FROM.value,
                            str(claim_id),
                            str(chunk.chunk_id),
                        ),
                        relationship_type=StructuralRelationshipType.DERIVED_FROM.value,
                        tenant_id=tenant_id,
                        source_node_id=claim_id,
                        target_node_id=chunk.chunk_id,
                    )
                )

            for measurement in extraction.measurements:
                measurement_id = deterministic_id(
                    str(tenant_id),
                    "measurement",
                    str(chunk.chunk_id),
                    measurement.name,
                    measurement.value,
                )
                nodes.append(
                    GraphNode(
                        node_id=measurement_id,
                        label=SemanticNodeLabel.MEASUREMENT.value,
                        tenant_id=tenant_id,
                        properties={
                            "name": measurement.name,
                            "value": measurement.value,
                            "unit": measurement.unit,
                            "confidence": measurement.confidence,
                        },
                    )
                )

            for relationship in extraction.relationships:
                source = entity_index.get(normalize_entity_name(relationship.source_entity))
                target = entity_index.get(normalize_entity_name(relationship.target_entity))
                if source is None or target is None:
                    continue
                props: dict[str, JsonValue] = {
                    "confidence": relationship.confidence,
                    "description": relationship.description,
                    "proposed_predicate": relationship.proposed_predicate,
                    "chunk_id": str(chunk.chunk_id),
                }
                relationships.append(
                    GraphRelationship(
                        relationship_id=deterministic_id(
                            str(tenant_id),
                            relationship.predicate.value,
                            str(source.entity_id),
                            str(target.entity_id),
                            str(chunk.chunk_id),
                        ),
                        relationship_type=relationship.predicate.value,
                        tenant_id=tenant_id,
                        source_node_id=source.entity_id,
                        target_node_id=target.entity_id,
                        properties=props,
                    )
                )

            for entity in entities:
                # Chunk mentions resolved entities present in this extraction.
                mentioned_names = {
                    normalize_entity_name(item.name) for item in extraction.entities
                }
                if entity.normalized_name not in mentioned_names:
                    continue
                relationships.append(
                    GraphRelationship(
                        relationship_id=deterministic_id(
                            str(tenant_id),
                            SemanticRelationshipType.MENTIONS.value,
                            str(chunk.chunk_id),
                            str(entity.entity_id),
                        ),
                        relationship_type=SemanticRelationshipType.MENTIONS.value,
                        tenant_id=tenant_id,
                        source_node_id=chunk.chunk_id,
                        target_node_id=entity.entity_id,
                    )
                )

        return ProjectedGraph(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            nodes=nodes,
            relationships=relationships,
        )
