"""Deletion, orphan rules and reindex tests."""

from __future__ import annotations

import pytest

from graph_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from graph_rag.application.deletion import DeleteDocumentService, ReindexScope
from graph_rag.application.graph import BuildKnowledgeGraphService
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.deletion import orphan_shared_entity_ids, related_shared_entity_ids
from graph_rag.domain.documents import NormalizedDocument, NormalizedPage, ParserInfo
from graph_rag.domain.elements import HeadingElement, TextElement
from graph_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from graph_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import DocumentRecord, DocumentVersionRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.cache import InMemoryCacheInvalidator
from graph_rag.infrastructure.models import FakeEmbeddingModel, FakeStructuredExtractor
from graph_rag.infrastructure.persistence.chunks import InMemoryChunkLookupStore
from graph_rag.infrastructure.persistence.memory import (
    InMemoryDocumentRepository,
    InMemoryObjectStore,
)
from graph_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from graph_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore
from graph_rag.shared.exceptions import NotFoundError


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _doc() -> NormalizedDocument:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    page_id = new_id()
    ids = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}
    return NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        source_filename="a.pdf",
        mime_type="application/pdf",
        title="A",
        page_count=1,
        pages=[NormalizedPage(page_id=page_id, page_number=1)],
        parser_info=ParserInfo(parser_name="docling", parser_version="1"),
        elements=[
            HeadingElement(
                element_id=new_id(),
                **ids,
                page_start=1,
                page_end=1,
                reading_order=0,
                section_path=["S"],
                content_hash=_hash("S"),
                level=1,
                normalized_content="S",
            ),
            TextElement(
                element_id=new_id(),
                **ids,
                page_start=1,
                page_end=1,
                reading_order=1,
                section_path=["S"],
                content_hash=_hash("body"),
                normalized_content="Silicone oil viscosity decreases with temperature.",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_shared_entity_survives_when_referenced_by_other_document() -> None:
    tenant = TenantContext(tenant_id=new_id())
    entity_id = new_id()
    chunk_a = new_id()
    chunk_b = new_id()
    version_a = new_id()
    version_b = new_id()
    doc_a = new_id()
    doc_b = new_id()
    store = InMemoryGraphStore()
    await store.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=doc_a,
            version_id=version_a,
            nodes=[
                GraphNode(
                    node_id=chunk_a,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "chunk_id": str(chunk_a),
                        "document_id": str(doc_a),
                        "version_id": str(version_a),
                    },
                ),
                GraphNode(
                    node_id=chunk_b,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "chunk_id": str(chunk_b),
                        "document_id": str(doc_b),
                        "version_id": str(version_b),
                    },
                ),
                GraphNode(
                    node_id=entity_id,
                    label=SemanticNodeLabel.CHEMICAL.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "canonical_name": "silicone oil",
                        "normalized_name": "silicone oil",
                    },
                ),
                GraphNode(
                    node_id=version_a,
                    label=StructuralNodeLabel.DOCUMENT_VERSION.value,
                    tenant_id=tenant.tenant_id,
                    properties={"document_id": str(doc_a), "version_id": str(version_a)},
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk_a,
                    target_node_id=entity_id,
                ),
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk_b,
                    target_node_id=entity_id,
                ),
            ],
        ),
    )
    deleted = await store.delete_version(
        tenant,
        document_id=doc_a,
        version_id=version_a,
        chunk_ids=[chunk_a],
    )
    assert deleted >= 1
    assert entity_id in store.nodes
    assert chunk_a not in store.nodes
    assert chunk_b in store.nodes


@pytest.mark.asyncio
async def test_orphan_entity_removed_when_last_mention_deleted() -> None:
    tenant = TenantContext(tenant_id=new_id())
    entity_id = new_id()
    chunk_id = new_id()
    version_id = new_id()
    document_id = new_id()
    store = InMemoryGraphStore()
    await store.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            nodes=[
                GraphNode(
                    node_id=chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "version_id": str(version_id),
                        "document_id": str(document_id),
                    },
                ),
                GraphNode(
                    node_id=entity_id,
                    label=SemanticNodeLabel.CHEMICAL.value,
                    tenant_id=tenant.tenant_id,
                    properties={"normalized_name": "silicone oil"},
                ),
                GraphNode(
                    node_id=version_id,
                    label=StructuralNodeLabel.DOCUMENT_VERSION.value,
                    tenant_id=tenant.tenant_id,
                    properties={},
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk_id,
                    target_node_id=entity_id,
                )
            ],
        ),
    )
    await store.delete_version(
        tenant,
        document_id=document_id,
        version_id=version_id,
        chunk_ids=[chunk_id],
    )
    assert entity_id not in store.nodes
    assert chunk_id not in store.nodes


def test_orphan_helpers() -> None:
    tenant_id = new_id()
    chunk = new_id()
    entity = new_id()
    nodes = {
        chunk: GraphNode(
            node_id=chunk,
            label="Chunk",
            tenant_id=tenant_id,
            properties={},
        ),
        entity: GraphNode(
            node_id=entity,
            label="Chemical",
            tenant_id=tenant_id,
            properties={},
        ),
    }
    rels = {
        new_id(): GraphRelationship(
            relationship_id=new_id(),
            relationship_type="MENTIONS",
            tenant_id=tenant_id,
            source_node_id=chunk,
            target_node_id=entity,
        )
    }
    related = related_shared_entity_ids(rels, tenant_id=tenant_id, chunk_ids={chunk})
    assert entity in related
    orphans = orphan_shared_entity_ids(
        nodes,
        {},
        tenant_id=tenant_id,
        removed_chunk_ids={chunk},
        candidate_entity_ids={entity},
    )
    assert entity in orphans


@pytest.mark.asyncio
async def test_delete_document_service_cleans_indexes() -> None:
    document = _doc()
    tenant = TenantContext(tenant_id=document.tenant_id)
    doc_repo = InMemoryDocumentRepository()
    await doc_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document.document_id,
            tenant_id=document.tenant_id,
            title="A",
            status=DocumentLifecycleStatus.READY,
            current_version_id=document.version_id,
        ),
    )
    await doc_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=document.version_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version_number=1,
            source_filename="a.pdf",
            mime_type="application/pdf",
            content_hash=_hash("a"),
            status=DocumentLifecycleStatus.READY,
            original_object_key=(
                f"tenants/{document.tenant_id}/documents/{document.document_id}/"
                f"versions/{document.version_id}/original/a.pdf"
            ),
        ),
    )
    object_store = InMemoryObjectStore()
    await object_store.put_bytes(
        tenant,
        object_key=(
            f"tenants/{document.tenant_id}/documents/{document.document_id}/"
            f"versions/{document.version_id}/original/a.pdf"
        ),
        data=b"%PDF",
        content_type="application/pdf",
        content_hash=_hash("pdf"),
    )
    chunks = HierarchicalMultimodalChunker().chunk(document)
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, chunks.all_chunks)
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(FakeEmbeddingModel()).embed(chunks.all_chunks)
    await vectors.upsert(tenant, embedded.records)
    graph = InMemoryGraphStore()
    await BuildKnowledgeGraphService(FakeStructuredExtractor(), graph).build(
        tenant, document, chunks
    )
    cache = InMemoryCacheInvalidator()
    service = DeleteDocumentService(
        document_repo=doc_repo,
        object_store=object_store,
        vector_store=vectors,
        graph_store=graph,
        cache=cache,
        chunk_id_provider=lambda t, d, v: [
            c.chunk_id for c in chunk_store.list_for_version(t, document_id=d, version_id=v)
        ],
    )
    result = await service.execute(tenant, document_id=document.document_id)
    assert result.status.value in {"completed", "partial"}
    assert result.vectors_deleted >= 1
    assert result.objects_deleted >= 1
    assert result.cache_keys_invalidated == 1
    updated = await doc_repo.get_document(tenant, document.document_id)
    assert updated is not None
    assert updated.status is DocumentLifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_reindex_clears_vectors_and_enqueues_run() -> None:
    container = build_local_container()
    tenant = await container.resolve_tenant(tenant_key="demo")
    # Register a tiny PDF via register service path is heavy; seed repos directly.
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    assert container.ingestion_repo is not None
    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="reindex",
            status=DocumentLifecycleStatus.READY,
            current_version_id=version_id,
        ),
    )
    await container.document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="r.pdf",
            mime_type="application/pdf",
            content_hash=_hash("r"),
            status=DocumentLifecycleStatus.READY,
        ),
    )
    assert container.reindex_document is not None
    result = await container.reindex_document.execute(
        tenant,
        document_id=document_id,
        scope=ReindexScope.VECTORS,
    )
    assert result.ingestion_run_id is not None
    assert result.scope is ReindexScope.VECTORS
    run = await container.ingestion_repo.get_run(tenant, result.ingestion_run_id)
    assert run is not None
    assert run.metadata.get("reindex_scope") == "vectors"


@pytest.mark.asyncio
async def test_reindex_full_scope_clears_parse_artifacts_and_resumes_at_parse() -> None:
    """FULL must reprocess from scratch, not just rebuild indexes from cache.

    Regression test: FULL previously resumed at CHUNK and never cleared
    parse_raw/normalized, so stage_parse/stage_normalize's own
    (tenant, document, version)-keyed artifact caches meant a "full"
    reprocess silently kept serving whatever PARSE produced on first
    ingest -- a parser fix (e.g. new bounding-box extraction) never
    reached already-ingested documents without a fresh re-upload.
    """
    from graph_rag.application.ingestion.stage_pipeline import artifact_key

    container = build_local_container()
    tenant, document_id, version_id = await _seed_document_intelligence_reindex_fixture(container)
    assert container.object_store is not None

    seeded_names = ("parse_raw", "normalized", "chunks", "embeddings", "graph")
    for name in seeded_names:
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        await container.object_store.put_bytes(
            tenant,
            object_key=key,
            data=b"{}",
            content_type="application/json",
            content_hash=_hash(name),
        )

    assert container.reindex_document is not None
    result = await container.reindex_document.execute(
        tenant,
        document_id=document_id,
        scope=ReindexScope.FULL,
    )

    for name in seeded_names:
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        with pytest.raises(NotFoundError):
            await container.object_store.get_bytes(tenant, object_key=key)

    assert container.ingestion_repo is not None
    run = await container.ingestion_repo.get_run(tenant, result.ingestion_run_id)
    assert run is not None
    assert run.metadata.get("resume_stage") == "PARSE"


async def _seed_document_intelligence_reindex_fixture(container):
    """Shared setup for the DOCUMENT_INTELLIGENCE-scope reindex tests below."""
    tenant = await container.resolve_tenant(tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="reindex-di",
            status=DocumentLifecycleStatus.READY,
            current_version_id=version_id,
        ),
    )
    await container.document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="r.pdf",
            mime_type="application/pdf",
            content_hash=_hash("r"),
            status=DocumentLifecycleStatus.READY,
        ),
    )
    return tenant, document_id, version_id


@pytest.mark.asyncio
async def test_reindex_document_intelligence_scope_clears_derived_artifacts_only() -> None:
    from graph_rag.application.ingestion.stage_pipeline import artifact_key

    container = build_local_container()
    tenant, document_id, version_id = await _seed_document_intelligence_reindex_fixture(container)
    assert container.object_store is not None

    seeded_names = ("parse_raw", "normalized", "chunks", "embeddings", "graph")
    for name in seeded_names:
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        await container.object_store.put_bytes(
            tenant,
            object_key=key,
            data=b"{}",
            content_type="application/json",
            content_hash=_hash(name),
        )

    assert container.reindex_document is not None
    from graph_rag.application.document_intelligence.models import (
        DocumentIntelligenceIngestOptions,
    )

    await container.reindex_document.execute(
        tenant,
        document_id=document_id,
        scope=ReindexScope.DOCUMENT_INTELLIGENCE,
        document_intelligence=DocumentIntelligenceIngestOptions(enabled=True, model_id="sds"),
    )

    for name in ("chunks", "embeddings", "graph"):
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        with pytest.raises(NotFoundError):
            await container.object_store.get_bytes(tenant, object_key=key)
    for name in ("parse_raw", "normalized"):
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        data = await container.object_store.get_bytes(tenant, object_key=key)
        assert data == b"{}"


@pytest.mark.asyncio
async def test_reindex_document_intelligence_scope_carries_options_into_run_metadata() -> None:
    from graph_rag.application.document_intelligence.models import (
        DocumentIntelligenceIngestOptions,
    )

    container = build_local_container()
    tenant, document_id, _version_id = await _seed_document_intelligence_reindex_fixture(container)
    assert container.reindex_document is not None
    assert container.ingestion_repo is not None

    options = DocumentIntelligenceIngestOptions(enabled=True, model_id="sds")
    result = await container.reindex_document.execute(
        tenant,
        document_id=document_id,
        scope=ReindexScope.DOCUMENT_INTELLIGENCE,
        document_intelligence=options,
    )
    assert result.ingestion_run_id is not None
    run = await container.ingestion_repo.get_run(tenant, result.ingestion_run_id)
    assert run is not None
    assert run.metadata.get("resume_stage") == "EXTRACT_DOCUMENT_INTELLIGENCE"
    assert run.metadata.get("document_intelligence") == options.model_dump(mode="json")


@pytest.mark.asyncio
async def test_reindex_document_intelligence_scope_requires_enabled_options() -> None:
    from graph_rag.application.document_intelligence.models import (
        DocumentIntelligenceIngestOptions,
    )
    from graph_rag.shared.exceptions import ValidationError

    container = build_local_container()
    tenant, document_id, _version_id = await _seed_document_intelligence_reindex_fixture(container)
    assert container.reindex_document is not None

    with pytest.raises(ValidationError):
        await container.reindex_document.execute(
            tenant,
            document_id=document_id,
            scope=ReindexScope.DOCUMENT_INTELLIGENCE,
            document_intelligence=None,
        )
    with pytest.raises(ValidationError):
        await container.reindex_document.execute(
            tenant,
            document_id=document_id,
            scope=ReindexScope.DOCUMENT_INTELLIGENCE,
            document_intelligence=DocumentIntelligenceIngestOptions(enabled=False),
        )


@pytest.mark.asyncio
async def test_container_submit_deletion_executes_cleanup() -> None:
    container = build_local_container()
    tenant = await container.resolve_tenant(tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="del",
            status=DocumentLifecycleStatus.READY,
            current_version_id=version_id,
        ),
    )
    await container.document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="d.pdf",
            mime_type="application/pdf",
            content_hash=_hash("d"),
            status=DocumentLifecycleStatus.READY,
        ),
    )
    operation = await container.submit_deletion(tenant, document_id)
    assert operation.result is not None
    assert operation.status in {"completed", "partial"}
