"""Knowledge-graph extraction, resolution and projection tests."""

from __future__ import annotations

import pytest

from enterprise_rag.application.chunking import HierarchicalMultimodalChunker
from enterprise_rag.application.graph import BuildKnowledgeGraphService
from enterprise_rag.domain.documents import NormalizedDocument, ParserInfo
from enterprise_rag.domain.documents.components import DocumentSection, NormalizedPage
from enterprise_rag.domain.elements import (
    CaptionElement,
    HeadingElement,
    ImageElement,
    TextElement,
)
from enterprise_rag.domain.graph import (
    EntityResolver,
    EntityType,
    ExtractedEntity,
    MergeStrategy,
    StructuralGraphBuilder,
    StructuralNodeLabel,
    StructuralRelationshipType,
    assert_node_label,
    merge_node_cypher,
    normalize_entity_name,
)
from enterprise_rag.domain.graph.cypher_safety import assert_relationship_type
from enterprise_rag.domain.ids import content_sha256_hex, deterministic_id, new_id
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeStructuredExtractor
from enterprise_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from enterprise_rag.shared.exceptions import ValidationError


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _document() -> NormalizedDocument:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    ids = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}
    page_id = deterministic_id(str(tenant_id), str(document_id), str(version_id), "page:1")
    section_id = deterministic_id(
        str(tenant_id), str(document_id), str(version_id), "section:Results"
    )
    heading = HeadingElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=0,
        section_path=["Results"],
        content_hash=_hash("Results"),
        level=1,
        normalized_content="Results",
    )
    text = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=1,
        section_path=["Results"],
        content_hash=_hash("body"),
        normalized_content="Acme Viscosity Lab measured silicone oil.",
    )
    image = ImageElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=2,
        section_path=["Results"],
        content_hash=_hash("img"),
        visual_description="Oil sample photo",
    )
    caption = CaptionElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=3,
        section_path=["Results"],
        content_hash=_hash("cap"),
        normalized_content="Figure 1",
        target_element_id=image.element_id,
    )
    return NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        title="Oil Study",
        source_filename="oil.pdf",
        mime_type="application/pdf",
        page_count=1,
        pages=[NormalizedPage(page_id=page_id, page_number=1)],
        sections=[
            DocumentSection(
                section_id=section_id,
                title="Results",
                level=1,
                path=["Results"],
                page_start=1,
                page_end=1,
            )
        ],
        elements=[heading, text, image, caption],
        parser_info=ParserInfo(parser_name="docling"),
    )


def test_normalize_entity_name() -> None:
    assert normalize_entity_name("  Silicone-Oil!! ") == "silicone oil"


def test_entity_resolver_merges_acronym_and_alias() -> None:
    tenant_id = new_id()
    resolver = EntityResolver(tenant_id=tenant_id)
    first = resolver.resolve(
        ExtractedEntity(
            name="Acme Viscosity Lab",
            normalized_name="acme viscosity lab",
            entity_type=EntityType.ORGANIZATION,
            confidence=0.9,
        )
    )
    second = resolver.resolve(
        ExtractedEntity(
            name="AVL",
            normalized_name="avl",
            entity_type=EntityType.ORGANIZATION,
            confidence=0.8,
        )
    )
    assert second.entity_id == first.entity_id
    assert second.mention_count == 2
    assert any(d.merge_strategy is MergeStrategy.ACRONYM for d in resolver.decisions)


def test_entity_resolver_does_not_merge_on_fuzzy_alone_without_overlap() -> None:
    tenant_id = new_id()
    resolver = EntityResolver(tenant_id=tenant_id, fuzzy_threshold=0.5)
    a = resolver.resolve(
        ExtractedEntity(
            name="Alpha Compound",
            normalized_name="alpha compound",
            entity_type=EntityType.CHEMICAL,
            confidence=0.9,
        )
    )
    b = resolver.resolve(
        ExtractedEntity(
            name="Zeta Mixture",
            normalized_name="zeta mixture",
            entity_type=EntityType.CHEMICAL,
            confidence=0.9,
        )
    )
    assert a.entity_id != b.entity_id


def test_structural_graph_builder_emits_allowlisted_structure() -> None:
    document = _document()
    chunks = HierarchicalMultimodalChunker().chunk(document)
    graph = StructuralGraphBuilder().build(document, chunks)
    labels = {node.label for node in graph.nodes}
    assert StructuralNodeLabel.DOCUMENT.value in labels
    assert StructuralNodeLabel.DOCUMENT_VERSION.value in labels
    assert StructuralNodeLabel.PAGE.value in labels
    assert StructuralNodeLabel.SECTION.value in labels
    assert StructuralNodeLabel.IMAGE.value in labels
    assert StructuralNodeLabel.CHUNK.value in labels
    rel_types = {rel.relationship_type for rel in graph.relationships}
    assert StructuralRelationshipType.HAS_VERSION.value in rel_types
    assert StructuralRelationshipType.HAS_CAPTION.value in rel_types
    assert StructuralRelationshipType.NEXT_ELEMENT.value in rel_types


def test_cypher_templates_reject_unknown_labels() -> None:
    with pytest.raises(ValidationError):
        assert_node_label("EvilLabel")
    with pytest.raises(ValidationError):
        assert_relationship_type("HACKS")
    query = merge_node_cypher("Document")
    assert "MERGE (n:Document" in query
    assert "$tenant_id" in query


@pytest.mark.asyncio
async def test_build_knowledge_graph_end_to_end() -> None:
    document = _document()
    chunks = HierarchicalMultimodalChunker().chunk(document)
    store = InMemoryGraphStore()
    service = BuildKnowledgeGraphService(FakeStructuredExtractor(), store)
    tenant = TenantContext(tenant_id=document.tenant_id)
    result = await service.build(tenant, document, chunks)
    assert result.upsert_counts["nodes"] > 0
    assert result.upsert_counts["relationships"] > 0
    assert result.entities
    # Acme + AVL should resolve to one organization.
    orgs = [entity for entity in result.entities if entity.entity_type == "Organization"]
    assert len(orgs) == 1
    assert any(node.label == "Claim" for node in result.graph.nodes)
    assert any(node.label == "Measurement" for node in result.graph.nodes)
    assert any(
        rel.relationship_type == "MENTIONS" for rel in result.graph.relationships
    )
    deleted = await store.delete_version(
        tenant,
        document_id=document.document_id,
        version_id=document.version_id,
    )
    assert deleted >= 1
