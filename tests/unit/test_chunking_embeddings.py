"""Hierarchical chunking, embedding and vector-store tests."""

from __future__ import annotations

import pytest

from enterprise_rag.application.chunking import (
    EmbedChunksService,
    HierarchicalMultimodalChunker,
)
from enterprise_rag.config.settings import ChunkingSettings
from enterprise_rag.domain.chunks import ChunkType
from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.chunks.vectors import VectorSearchRequest
from enterprise_rag.domain.documents import NormalizedDocument, ParserInfo
from enterprise_rag.domain.elements import (
    CaptionElement,
    EquationElement,
    HeadingElement,
    ImageElement,
    TableData,
    TableElement,
    TextElement,
)
from enterprise_rag.domain.elements.table import TableCell
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import (
    FakeEmbeddingModel,
    LangChainOpenAIEmbeddingModel,
    OpenAIEmbeddingModel,
)
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore
from enterprise_rag.shared.exceptions import AuthorizationError


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _sample_document() -> NormalizedDocument:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    ids = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}
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
    prose = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=1,
        section_path=["Results"],
        content_hash=_hash("prose"),
        normalized_content="Measured viscosity declined with temperature.",
    )
    image = ImageElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=2,
        section_path=["Results"],
        content_hash=_hash("image"),
        visual_description="Viscosity plot thumbnail",
        raw_content="[image]",
    )
    caption = CaptionElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=3,
        section_path=["Results"],
        content_hash=_hash("cap"),
        normalized_content="Figure 2. Viscosity trend",
        target_element_id=image.element_id,
    )
    table = TableElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=4,
        section_path=["Results"],
        content_hash=_hash("table"),
        table=TableData(
            caption="Table A",
            markdown="| Temp | Viscosity |\n| 20 | 12 |\n| 40 | 8 |",
            column_headers=["Temp", "Viscosity"],
            cells=[
                TableCell(row_index=0, column_index=0, text="20"),
                TableCell(row_index=0, column_index=1, text="12"),
                TableCell(row_index=1, column_index=0, text="40"),
                TableCell(row_index=1, column_index=1, text="8"),
            ],
            semantic_summary="Temperature versus viscosity",
        ),
    )
    equation = EquationElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=5,
        section_path=["Results"],
        content_hash=_hash("eq"),
        latex="eta = a/T",
        semantic_description="Viscosity inversely related to temperature",
    )
    explanation = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=6,
        section_path=["Results"],
        content_hash=_hash("explain"),
        normalized_content="This relation fits the observed values.",
    )
    return NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        title="Viscosity Study",
        source_filename="study.pdf",
        mime_type="application/pdf",
        page_count=0,
        elements=[heading, prose, image, caption, table, equation, explanation],
        parser_info=ParserInfo(parser_name="docling"),
    )


def test_hierarchical_chunker_builds_parent_child_and_composites() -> None:
    document = _sample_document()
    result = HierarchicalMultimodalChunker().chunk(document)
    assert len(result.parents) == 1
    assert result.parents[0].chunk_type is ChunkType.SECTION
    assert all(child.parent_chunk_id == result.parents[0].chunk_id for child in result.children)

    types = {child.chunk_type for child in result.children}
    assert ChunkType.TEXT in types
    assert ChunkType.IMAGE in types
    assert ChunkType.MULTIMODAL_COMPOSITE in types
    assert ChunkType.TABLE in types
    assert ChunkType.TABLE_ROW in types
    assert ChunkType.EQUATION in types

    equation = next(child for child in result.children if child.chunk_type is ChunkType.EQUATION)
    assert "fits the observed" in equation.text


def test_chunker_can_disable_row_and_composite_chunks() -> None:
    document = _sample_document()
    settings = ChunkingSettings(
        generate_table_row_chunks=False,
        generate_composite_chunks=False,
    )
    result = HierarchicalMultimodalChunker(settings).chunk(document)
    types = {child.chunk_type for child in result.children}
    assert ChunkType.TABLE_ROW not in types
    assert ChunkType.MULTIMODAL_COMPOSITE not in types


def test_chunker_flushes_text_on_page_boundary() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    ids = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}
    page_a = TextElement(
        element_id=new_id(),
        **ids,
        page_start=53,
        page_end=53,
        reading_order=0,
        section_path=["(document)"],
        content_hash=_hash("p53"),
        normalized_content="Comparison with synthetic mica Appearance Samples",
    )
    page_b = TextElement(
        element_id=new_id(),
        **ids,
        page_start=55,
        page_end=55,
        reading_order=1,
        section_path=["(document)"],
        content_hash=_hash("p55"),
        normalized_content="Soft-focus effect Transparent BYK-mac",
    )
    document = NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        title="Deck",
        source_filename="deck.pdf",
        mime_type="application/pdf",
        page_count=55,
        elements=[page_a, page_b],
        parser_info=ParserInfo(parser_name="pdfium_multimodal"),
    )
    result = HierarchicalMultimodalChunker().chunk(document)
    text_children = [
        child for child in result.children if child.chunk_type is ChunkType.TEXT
    ]
    assert len(text_children) == 2
    assert {(c.page_start, c.page_end) for c in text_children} == {(53, 53), (55, 55)}


@pytest.mark.asyncio
async def test_embed_and_inmemory_search_enforces_tenant() -> None:
    document = _sample_document()
    chunks = HierarchicalMultimodalChunker().chunk(document).all_chunks
    embedder = FakeEmbeddingModel()
    embedded = await EmbedChunksService(embedder).embed(chunks, parser="docling")
    assert embedded.records
    assert all(record.payload.parser == "docling" for record in embedded.records)

    store = InMemoryChunkVectorStore()
    await store.ensure_collection(vector_size=len(embedded.records[0].content_vector))
    tenant = TenantContext(tenant_id=document.tenant_id)
    written = await store.upsert(tenant, embedded.records)
    assert written == len(embedded.records)

    hits = await store.search(
        tenant,
        VectorSearchRequest(
            tenant_id=document.tenant_id,
            query_vector=embedded.records[0].content_vector,
            top_k=5,
        ),
    )
    assert hits
    assert hits[0].payload.tenant_id == document.tenant_id

    other = TenantContext(tenant_id=new_id())
    with pytest.raises(AuthorizationError):
        await store.search(
            other,
            VectorSearchRequest(
                tenant_id=document.tenant_id,
                query_vector=embedded.records[0].content_vector,
            ),
        )

    deleted = await store.delete_version(
        tenant,
        document_id=document.document_id,
        version_id=document.version_id,
    )
    assert deleted == written


@pytest.mark.asyncio
async def test_embed_skips_empty_chunks_instead_of_failing_whole_batch() -> None:
    """A blank chunk (e.g. a slide that's pure image, no extractable text)
    must not take the whole document down. OpenAI's embeddings endpoint
    rejects an empty/whitespace-only input with a 400 for the *entire*
    batch it's part of — so filtering has to happen before the call, not
    after. Regression for exactly that: a real document failed ingestion
    entirely because one chunk among many had empty text.
    """
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    ids = {"tenant_id": tenant_id, "document_id": document_id, "version_id": version_id}

    def _chunk(text: str) -> ChunkBase:
        return ChunkBase(
            chunk_id=new_id(),
            **ids,
            modality=Modality.TEXT,
            chunk_type=ChunkType.TEXT,
            text=text,
            token_count=len(text.split()),
            page_start=1,
            page_end=1,
            content_hash=_hash(text or "empty"),
        )

    chunks = [_chunk("Real extractable content."), _chunk(""), _chunk("   "), _chunk("More text.")]

    result = await EmbedChunksService(FakeEmbeddingModel()).embed(chunks)

    assert result.skipped_empty == 2
    assert len(result.records) == 2
    assert {record.point_id for record in result.records} == {
        chunks[0].chunk_id,
        chunks[3].chunk_id,
    }


@pytest.mark.asyncio
async def test_embedding_adapters_with_injected_fn() -> None:
    def embed_fn(texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]

    lc = LangChainOpenAIEmbeddingModel(embed_fn=embed_fn)
    oa = OpenAIEmbeddingModel(embed_fn=embed_fn)
    for model in (lc, oa):
        response = await model.embed_documents(["abc", "abcd"])
        assert response == [[3.0, 1.0], [4.0, 1.0]]
        query = await model.embed_query("hi")
        assert query == [2.0, 1.0]


def test_modality_filters_on_search_payload() -> None:
    # Ensure modality enum used by chunker is searchable vocabulary.
    assert Modality.COMPOSITE.value == "composite"
    assert ChunkType.MULTIMODAL_COMPOSITE.value == "multimodal_composite"
