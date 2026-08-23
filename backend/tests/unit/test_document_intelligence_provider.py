"""InternalExtractionProvider cheap-tier extraction chain tests (Phase 4)."""

from __future__ import annotations

import pytest

from graph_rag.application.document_intelligence.models import (
    ConfidenceBand,
    DocumentIntelligenceExtractionRequest,
    ExtractionMethod,
    FieldType,
    ModelFieldSpec,
)
from graph_rag.application.document_intelligence.providers.internal import (
    EMBEDDING_CONFIDENCE_CAP,
    InternalExtractionProvider,
)
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.elements import TableData, TableElement, TextElement
from graph_rag.domain.elements.table import TableCell
from graph_rag.domain.ids import content_sha256_hex, new_id

_TENANT_ID = new_id()
_DOCUMENT_ID = new_id()
_VERSION_ID = new_id()


def _ids() -> dict:
    return {"tenant_id": _TENANT_ID, "document_id": _DOCUMENT_ID, "version_id": _VERSION_ID}


def _text_element(content: str, *, page: int = 1, order: int = 0) -> TextElement:
    return TextElement(
        element_id=new_id(),
        **_ids(),
        page_start=page,
        page_end=page,
        reading_order=order,
        normalized_content=content,
        content_hash=content_sha256_hex(content),
    )


def _table_element(table: TableData, *, page: int = 1, order: int = 0) -> TableElement:
    return TableElement(
        element_id=new_id(),
        **_ids(),
        page_start=page,
        page_end=page,
        reading_order=order,
        content_hash=content_sha256_hex(table.markdown or "table"),
        table=table,
    )


def _document(elements=(), *, title=None, page_count=1, language=None, metadata=None):
    return NormalizedDocument(
        tenant_id=_TENANT_ID,
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        title=title,
        source_filename="doc.pdf",
        mime_type="application/pdf",
        language=language,
        page_count=page_count,
        metadata=metadata or {},
        elements=list(elements),
        parser_info=ParserInfo(parser_name="docling", parser_version="1.0"),
    )


class _NullEmbeddingModel:
    async def embed(self, request):  # pragma: no cover - not exercised
        raise NotImplementedError

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0, 0.0]


class _FakeEmbeddingModel:
    """Deterministic embeddings from an explicit text->vector table.

    Unlike the generic ``FakeEmbeddingModel`` used elsewhere, these vectors
    are semantically meaningful *by construction* for this test's spans and
    queries, so similarity ranking is fully controlled and predictable.
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, request):  # pragma: no cover - not exercised
        raise NotImplementedError

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vectors[text]


@pytest.mark.asyncio
async def test_structured_parser_tier_resolves_schema_and_metadata_fields() -> None:
    document = _document(title="SDS Report", page_count=3, metadata={"revision": "v2"})
    fields = [
        ModelFieldSpec(name="title", label="Title", field_type=FieldType.STRING),
        ModelFieldSpec(name="revision", label="Revision", field_type=FieldType.STRING),
        ModelFieldSpec(name="not_present", label="Not present", field_type=FieldType.STRING),
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    by_name = {field.name: field for field in result.fields}
    assert by_name["title"].value == "SDS Report"
    assert by_name["title"].extraction_method is ExtractionMethod.STRUCTURED_PARSER
    assert by_name["title"].confidence_band is ConfidenceBand.HIGH
    assert by_name["revision"].value == "v2"
    assert by_name["revision"].confidence_band is ConfidenceBand.MEDIUM
    assert "not_present" in result.unresolved_field_names


@pytest.mark.asyncio
async def test_rules_tier_matches_label_and_field_name() -> None:
    document = _document(
        elements=[
            _text_element("Product Name: Acme Widget", order=0),
            _text_element("Warranty period: 12 months", order=1),
        ]
    )
    fields = [
        ModelFieldSpec(name="product_name", label="Product Name", field_type=FieldType.STRING),
        # label differs from the document text -- only the name-as-label
        # candidate ("warranty period") can match this line.
        ModelFieldSpec(name="warranty_period", label="Coverage Term", field_type=FieldType.STRING),
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    by_name = {field.name: field for field in result.fields}
    assert by_name["product_name"].value == "Acme Widget"
    assert by_name["product_name"].extraction_method is ExtractionMethod.RULES
    assert by_name["warranty_period"].value == "12 months"


@pytest.mark.asyncio
async def test_rules_tier_rejects_non_date_shaped_capture() -> None:
    document = _document(elements=[_text_element("Manufacture Year: banana")])
    fields = [
        ModelFieldSpec(name="manufacture_year", label="Manufacture Year", field_type=FieldType.DATE)
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields == []
    assert result.unresolved_field_names == ["manufacture_year"]


@pytest.mark.asyncio
async def test_low_confidence_string_match_is_surfaced_not_hidden() -> None:
    """The literal design requirement: a LOW-band result is never filtered out."""
    document = _document(elements=[_text_element("Batch Number: BN-1")])
    fields = [
        ModelFieldSpec(name="batch_number", label="Batch Number", field_type=FieldType.STRING)
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert len(result.fields) == 1
    assert result.fields[0].confidence_band is ConfidenceBand.LOW
    assert result.fields[0].value == "BN-1"


@pytest.mark.asyncio
async def test_table_extraction_tier_horizontal_sibling() -> None:
    table = TableData(
        cells=[
            TableCell(row_index=0, column_index=0, text="Batch Number", is_row_header=True),
            TableCell(row_index=0, column_index=1, text="BN-4521"),
        ]
    )
    document = _document(elements=[_table_element(table)])
    fields = [
        ModelFieldSpec(name="batch_number", label="Batch Number", field_type=FieldType.STRING)
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == "BN-4521"
    assert result.fields[0].extraction_method is ExtractionMethod.TABLE_EXTRACTION
    assert result.fields[0].confidence == 0.80


@pytest.mark.asyncio
async def test_table_extraction_tier_vertical_sibling_single_data_row() -> None:
    table = TableData(
        cells=[
            TableCell(row_index=0, column_index=0, text="Lot Number", is_column_header=True),
            TableCell(row_index=1, column_index=0, text="LOT-99"),
        ]
    )
    document = _document(elements=[_table_element(table)])
    fields = [ModelFieldSpec(name="lot_number", label="Lot Number", field_type=FieldType.STRING)]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == "LOT-99"
    assert result.fields[0].confidence == 0.65


@pytest.mark.asyncio
async def test_whole_table_capture_for_table_field_type() -> None:
    table = TableData(markdown="| A | B |\n|---|---|\n| x | y |")
    document = _document(elements=[_table_element(table)])
    fields = [ModelFieldSpec(name="test_results", label="Test results", field_type=FieldType.TABLE)]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == table.markdown
    assert result.fields[0].confidence == 0.75


@pytest.mark.asyncio
async def test_two_tables_one_table_field_first_table_wins() -> None:
    first = TableData(markdown="| first |")
    second = TableData(markdown="| second |")
    document = _document(
        elements=[
            _table_element(first, order=0),
            _table_element(second, order=1),
        ]
    )
    fields = [
        ModelFieldSpec(name="specifications", label="Specifications", field_type=FieldType.TABLE)
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == "| first |"
    assert result.fields[0].confidence == 0.55


@pytest.mark.asyncio
async def test_embedding_tier_prefers_on_topic_span_and_caps_confidence() -> None:
    on_topic = "The product is manufactured using a proprietary cold-press process."
    off_topic = "Unrelated boilerplate about shipping terms and conditions."
    query = "Manufacturing process (manufacturing_process)"
    document = _document(
        elements=[_text_element(on_topic, order=0), _text_element(off_topic, order=1)]
    )
    fields = [
        ModelFieldSpec(
            name="manufacturing_process", label="Manufacturing process", field_type=FieldType.STRING
        )
    ]
    embedding_model = _FakeEmbeddingModel(
        {
            on_topic: [1.0, 0.0],
            off_topic: [0.0, 1.0],
            query: [1.0, 0.0],
        }
    )
    provider = InternalExtractionProvider(embedding_model=embedding_model)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert len(result.fields) == 1
    field = result.fields[0]
    assert field.extraction_method is ExtractionMethod.EMBEDDING_SEMANTIC
    assert field.source_text == on_topic
    assert field.confidence <= EMBEDDING_CONFIDENCE_CAP


@pytest.mark.asyncio
async def test_embedding_tier_below_floor_yields_no_match() -> None:
    span = "Completely unrelated text about warehouse logistics."
    query = "Chemical composition (chemical_composition)"
    document = _document(elements=[_text_element(span)])
    fields = [
        ModelFieldSpec(
            name="chemical_composition", label="Chemical composition", field_type=FieldType.STRING
        )
    ]
    # Orthogonal vectors -> cosine similarity 0.0, well below the match floor.
    embedding_model = _FakeEmbeddingModel({span: [0.0, 1.0], query: [1.0, 0.0]})
    provider = InternalExtractionProvider(embedding_model=embedding_model)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields == []
    assert result.unresolved_field_names == ["chemical_composition"]


@pytest.mark.asyncio
async def test_partial_extraction_reports_exactly_the_missing_fields() -> None:
    document = _document(title="Report", elements=[_text_element("Product Name: Acme Widget")])
    fields = [
        ModelFieldSpec(name="title", label="Title", field_type=FieldType.STRING),
        ModelFieldSpec(name="product_name", label="Product Name", field_type=FieldType.STRING),
        ModelFieldSpec(name="missing_one", label="Missing one", field_type=FieldType.STRING),
        ModelFieldSpec(name="missing_two", label="Missing two", field_type=FieldType.STRING),
    ]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert {field.name for field in result.fields} == {"title", "product_name"}
    assert set(result.unresolved_field_names) == {"missing_one", "missing_two"}


@pytest.mark.asyncio
async def test_one_field_tier_failure_does_not_sink_the_whole_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from graph_rag.application.document_intelligence.providers import internal as internal_module

    document = _document(elements=[_text_element("Product Name: Acme Widget")])
    fields = [
        ModelFieldSpec(name="product_name", label="Product Name", field_type=FieldType.STRING),
        ModelFieldSpec(name="explodes", label="Explodes", field_type=FieldType.STRING),
    ]
    real_rules_tier = internal_module._rules_tier

    def _flaky_rules_tier(document, field):
        if field.name == "explodes":
            raise RuntimeError("garbage element content")
        return real_rules_tier(document, field)

    monkeypatch.setattr(internal_module, "_rules_tier", _flaky_rules_tier)
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert "product_name" in {field.name for field in result.fields}
    assert "explodes" in result.unresolved_field_names
