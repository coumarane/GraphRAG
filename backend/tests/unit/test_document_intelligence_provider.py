"""InternalExtractionProvider extraction chain tests (Phases 4-5)."""

from __future__ import annotations

from pathlib import Path

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
    LLM_CONFIDENCE_CAP,
    VISION_CONFIDENCE_CAP,
    InternalExtractionProvider,
)
from graph_rag.application.usage.context import usage_context
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.elements import TableData, TableElement, TextElement
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.table import TableCell
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.models.contracts import (
    GenerationRequest,
    GenerationResponse,
    ModelCallMetadata,
    ModelRole,
    TokenUsage,
)
from graph_rag.domain.parsing.types import RawElement, RawParserResult
from graph_rag.domain.usage.models import UsageCapability
from graph_rag.infrastructure.models.openai_direct import OpenAIChatModel
from graph_rag.infrastructure.persistence.memory.usage import InMemoryUsageRepository

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


class _FakeChatModel:
    """Deterministic chat/vision model, one canned response per call in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return GenerationResponse(
            text=self._responses[index],
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-chat",
                role=request.role,
                usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            ),
        )


def _raw_result_with_image_pages(pages: list[int]) -> RawParserResult:
    return RawParserResult(
        parser_name="test",
        page_count=max(pages),
        elements=[
            RawElement(
                element_type=ElementType.IMAGE,
                page_start=page,
                page_end=page,
                reading_order=index,
            )
            for index, page in enumerate(pages)
        ],
    )


_SAMPLE_PDF = Path("../data/examples/sample.pdf")


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


@pytest.mark.asyncio
async def test_llm_tier_resolves_field_cheap_tiers_miss() -> None:
    document = _document(
        elements=[
            _text_element("This product uses eco-friendly packaging materials sourced locally.")
        ]
    )
    fields = [
        ModelFieldSpec(name="sourcing_note", label="Sourcing note", field_type=FieldType.STRING)
    ]
    chat = _FakeChatModel(
        ['{"fields": {"sourcing_note": {"value": "eco-friendly, local", "confidence": 0.7}}}']
    )
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].extraction_method is ExtractionMethod.LLM
    assert result.fields[0].value == "eco-friendly, local"


@pytest.mark.asyncio
async def test_llm_tier_null_value_leaves_field_unresolved() -> None:
    document = _document(elements=[_text_element("Some unrelated text.")])
    fields = [
        ModelFieldSpec(name="mystery_field", label="Mystery field", field_type=FieldType.STRING)
    ]
    chat = _FakeChatModel(['{"fields": {"mystery_field": {"value": null, "confidence": null}}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields == []
    assert result.unresolved_field_names == ["mystery_field"]


@pytest.mark.asyncio
async def test_llm_tier_confidence_capped() -> None:
    document = _document(elements=[_text_element("Full details about the product line here.")])
    fields = [ModelFieldSpec(name="summary", label="Summary", field_type=FieldType.STRING)]
    chat = _FakeChatModel(
        ['{"fields": {"summary": {"value": "Product line details", "confidence": 1.0}}}']
    )
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].confidence == LLM_CONFIDENCE_CAP


@pytest.mark.asyncio
async def test_llm_tier_degrades_gracefully_on_malformed_response() -> None:
    document = _document(elements=[_text_element("Some text content for the document.")])
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]

    fenced = _FakeChatModel(
        ['```json\n{"fields": {"foo": {"value": "bar", "confidence": 0.6}}}\n```']
    )
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=fenced)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == "bar"

    garbage = _FakeChatModel(["not json at all, sorry"])
    provider2 = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=garbage
    )
    result2 = await provider2.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result2.fields == []
    assert result2.unresolved_field_names == ["foo"]


@pytest.mark.asyncio
async def test_llm_tier_excludes_table_fields_from_prompt() -> None:
    document = _document(elements=[_text_element("Text content here for context.")])
    fields = [
        ModelFieldSpec(name="notes", label="Notes", field_type=FieldType.STRING),
        ModelFieldSpec(name="spec_table", label="Spec table", field_type=FieldType.TABLE),
    ]
    chat = _FakeChatModel(['{"fields": {"notes": {"value": "some notes", "confidence": 0.6}}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    await provider.extract(DocumentIntelligenceExtractionRequest(document=document, fields=fields))
    assert len(chat.calls) == 1
    prompt_text = str(chat.calls[0].messages[-1].content)
    assert "spec_table" not in prompt_text
    assert "notes" in prompt_text


@pytest.mark.asyncio
async def test_llm_tier_noop_without_chat_model() -> None:
    document = _document(elements=[_text_element("Some content here.")])
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel())
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields == []
    assert result.unresolved_field_names == ["foo"]


@pytest.mark.asyncio
async def test_llm_tier_disabled_by_settings() -> None:
    document = _document(elements=[_text_element("Some content here.")])
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    chat = _FakeChatModel(['{"fields": {"foo": {"value": "bar"}}}'])
    provider = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=chat, enable_llm_tier=False
    )
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert chat.calls == []
    assert result.fields == []


@pytest.mark.asyncio
async def test_llm_tier_failure_does_not_sink_the_whole_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from graph_rag.application.document_intelligence.providers import internal as internal_module

    document = _document(elements=[_text_element("Product Name: Acme Widget")])
    fields = [
        ModelFieldSpec(name="product_name", label="Product Name", field_type=FieldType.STRING),
        ModelFieldSpec(name="llm_only", label="LLM only field", field_type=FieldType.STRING),
    ]

    async def _boom(chat_model, document, fields):
        raise RuntimeError("model call failed")

    monkeypatch.setattr(internal_module, "_llm_tier", _boom)
    chat = _FakeChatModel(["{}"])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert "product_name" in {field.name for field in result.fields}
    assert "llm_only" in result.unresolved_field_names


@pytest.mark.asyncio
async def test_llm_tier_batches_all_remaining_fields_in_one_call() -> None:
    document = _document(
        elements=[_text_element("Rich descriptive text about the product and its features.")]
    )
    fields = [
        ModelFieldSpec(name="field_a", label="Field A", field_type=FieldType.STRING),
        ModelFieldSpec(name="field_b", label="Field B", field_type=FieldType.STRING),
        ModelFieldSpec(name="field_c", label="Field C", field_type=FieldType.STRING),
    ]
    chat = _FakeChatModel(['{"fields": {"field_a": {"value": "A"}, "field_b": {"value": "B"}}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert len(chat.calls) == 1
    assert chat.calls[0].role == ModelRole.TEXT
    assert {field.name for field in result.fields} == {"field_a", "field_b"}


@pytest.mark.asyncio
async def test_llm_tier_resolves_object_field_with_nested_dict() -> None:
    document = _document(elements=[_text_element("Dimensions: 10cm x 5cm x 2cm, weight 200g.")])
    fields = [ModelFieldSpec(name="dimensions", label="Dimensions", field_type=FieldType.OBJECT)]
    chat = _FakeChatModel(
        [
            '{"fields": {"dimensions": {"value": {"length_cm": 10, "width_cm": 5, '
            '"height_cm": 2}, "confidence": 0.7}}}'
        ]
    )
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert result.fields[0].value == {"length_cm": 10, "width_cm": 5, "height_cm": 2}
    assert result.fields[0].extraction_method is ExtractionMethod.LLM


@pytest.mark.asyncio
async def test_vision_tier_skipped_without_raw_result_or_bytes() -> None:
    document = _document(elements=[_text_element("Some content.")])
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    chat = _FakeChatModel(['{"fields": {}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(document=document, fields=fields)
    )
    assert len(chat.calls) == 1
    assert result.fields == []


@pytest.mark.asyncio
async def test_vision_tier_skipped_when_no_visual_targets() -> None:
    document = _document(elements=[_text_element("Some content.")])
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = RawParserResult(parser_name="test", page_count=1, elements=[])
    chat = _FakeChatModel(['{"fields": {}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=document, fields=fields, raw_parser_result=raw, document_bytes=b"%PDF-1.4"
        )
    )
    assert len(chat.calls) == 1
    assert result.fields == []


@pytest.mark.asyncio
async def test_vision_tier_resolves_field_from_rendered_page() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    document = _document()
    fields = [ModelFieldSpec(name="visual_note", label="Visual note", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1])
    chat = _FakeChatModel(
        ['{"fields": {"visual_note": {"value": "Diagram shows X", "confidence": 0.5}}}']
    )
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=document,
            fields=fields,
            raw_parser_result=raw,
            document_bytes=_SAMPLE_PDF.read_bytes(),
        )
    )
    assert result.fields[0].extraction_method is ExtractionMethod.VISION
    assert result.fields[0].value == "Diagram shows X"
    assert result.fields[0].confidence <= VISION_CONFIDENCE_CAP


@pytest.mark.asyncio
async def test_vision_tier_caps_by_distinct_pages_not_targets() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    document = _document()
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    document_bytes = _SAMPLE_PDF.read_bytes()

    raw_three_pages = _raw_result_with_image_pages([1, 2, 3])
    chat_a = _FakeChatModel(['{"fields": {}}'])
    provider_a = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=chat_a, vision_max_pages=1
    )
    await provider_a.extract(
        DocumentIntelligenceExtractionRequest(
            document=document,
            fields=fields,
            raw_parser_result=raw_three_pages,
            document_bytes=document_bytes,
        )
    )
    assert len(chat_a.calls) == 1

    raw_same_page_twice = _raw_result_with_image_pages([1, 1])
    chat_b = _FakeChatModel(['{"fields": {}}'])
    provider_b = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=chat_b, vision_max_pages=1
    )
    await provider_b.extract(
        DocumentIntelligenceExtractionRequest(
            document=document,
            fields=fields,
            raw_parser_result=raw_same_page_twice,
            document_bytes=document_bytes,
        )
    )
    assert len(chat_b.calls) == 1


@pytest.mark.asyncio
async def test_vision_tier_stops_early_once_all_fields_resolved() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    document = _document()
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1, 2])
    chat = _FakeChatModel(
        ['{"fields": {"foo": {"value": "resolved on page 1", "confidence": 0.5}}}']
    )
    provider = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=chat, vision_max_pages=0
    )
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=document,
            fields=fields,
            raw_parser_result=raw,
            document_bytes=_SAMPLE_PDF.read_bytes(),
        )
    )
    assert len(chat.calls) == 1
    assert result.fields[0].value == "resolved on page 1"


@pytest.mark.asyncio
async def test_vision_tier_confidence_strictly_below_llm_tier_confidence() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    llm_document = _document(
        elements=[_text_element("Some descriptive text content here for context.")]
    )
    llm_fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    llm_chat = _FakeChatModel(['{"fields": {"foo": {"value": "bar", "confidence": 0.95}}}'])
    llm_provider = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=llm_chat
    )
    llm_result = await llm_provider.extract(
        DocumentIntelligenceExtractionRequest(document=llm_document, fields=llm_fields)
    )

    vision_document = _document()
    vision_fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1])
    vision_chat = _FakeChatModel(['{"fields": {"foo": {"value": "bar", "confidence": 0.95}}}'])
    vision_provider = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=vision_chat
    )
    vision_result = await vision_provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=vision_document,
            fields=vision_fields,
            raw_parser_result=raw,
            document_bytes=_SAMPLE_PDF.read_bytes(),
        )
    )
    assert vision_result.fields[0].confidence < llm_result.fields[0].confidence


@pytest.mark.asyncio
async def test_vision_tier_page_failure_does_not_stop_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    from graph_rag.application.document_intelligence.providers import internal as internal_module

    document = _document()
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1])
    document_bytes = _SAMPLE_PDF.read_bytes()

    def _boom(*args: object, **kwargs: object) -> bytes:
        raise RuntimeError("render failed")

    monkeypatch.setattr(internal_module, "render_visual_png", _boom)
    chat = _FakeChatModel(['{"fields": {}}'])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=document, fields=fields, raw_parser_result=raw, document_bytes=document_bytes
        )
    )
    assert result.fields == []
    assert result.unresolved_field_names == ["foo"]


@pytest.mark.asyncio
async def test_vision_tier_disabled_by_settings() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    document = _document()
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1])
    chat = _FakeChatModel(['{"fields": {"foo": {"value": "bar"}}}'])
    provider = InternalExtractionProvider(
        embedding_model=_NullEmbeddingModel(), chat_model=chat, enable_vision_tier=False
    )
    result = await provider.extract(
        DocumentIntelligenceExtractionRequest(
            document=document,
            fields=fields,
            raw_parser_result=raw,
            document_bytes=_SAMPLE_PDF.read_bytes(),
        )
    )
    assert chat.calls == []
    assert result.fields == []


@pytest.mark.asyncio
async def test_llm_tier_call_is_recorded_as_a_usage_event() -> None:
    repo = InMemoryUsageRepository()

    def chat_fn(messages, model_name, temperature):
        return (
            '{"fields": {"summary": {"value": "Acme Corp", "confidence": 0.8}}}',
            TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        )

    chat = OpenAIChatModel(chat_fn=chat_fn, usage_recorder=repo)
    document = _document(elements=[_text_element("Some descriptive company text content here.")])
    fields = [ModelFieldSpec(name="summary", label="Summary", field_type=FieldType.STRING)]
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)

    with usage_context(tenant_id=new_id()):
        await provider.extract(
            DocumentIntelligenceExtractionRequest(document=document, fields=fields)
        )

    assert len(repo.events) == 1
    assert repo.events[0].role == "text"
    assert repo.events[0].capability is UsageCapability.CHAT_COMPLETIONS


@pytest.mark.asyncio
async def test_vision_tier_call_is_recorded_as_a_usage_event() -> None:
    if not _SAMPLE_PDF.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    repo = InMemoryUsageRepository()

    def chat_fn(messages, model_name, temperature):
        return (
            '{"fields": {"foo": {"value": "bar", "confidence": 0.5}}}',
            TokenUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )

    chat = OpenAIChatModel(chat_fn=chat_fn, usage_recorder=repo)
    document = _document()
    fields = [ModelFieldSpec(name="foo", label="Foo", field_type=FieldType.STRING)]
    raw = _raw_result_with_image_pages([1])
    provider = InternalExtractionProvider(embedding_model=_NullEmbeddingModel(), chat_model=chat)

    with usage_context(tenant_id=new_id()):
        await provider.extract(
            DocumentIntelligenceExtractionRequest(
                document=document,
                fields=fields,
                raw_parser_result=raw,
                document_bytes=_SAMPLE_PDF.read_bytes(),
            )
        )

    assert len(repo.events) == 1
    assert repo.events[0].role == "vision"
    assert repo.events[0].capability is UsageCapability.VISION
