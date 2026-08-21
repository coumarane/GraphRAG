# 03 — Domain and Data Model

## Identifiers

Use UUIDv7 for runtime entities. Use deterministic UUIDv5 or stable content-derived IDs for elements and chunks when safe.

Primary identifiers:

- `tenant_id`
- `document_id`
- `document_version_id`
- `ingestion_run_id`
- `page_id`
- `element_id`
- `asset_id`
- `parent_chunk_id`
- `child_chunk_id`
- `entity_id`
- `claim_id`

## Normalized document

```python
class NormalizedDocument(BaseModel):
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    title: str | None
    source_filename: str
    mime_type: str
    language: str | None
    page_count: int
    metadata: dict[str, JsonValue]
    pages: list[NormalizedPage]
    elements: list[DocumentElement]
    sections: list[DocumentSection]
    assets: list[DocumentAsset]
    references: list[ElementReference]
    parser_info: ParserInfo
```

## Element union

Use a discriminated union:

- `TextElement`
- `HeadingElement`
- `ListElement`
- `TableElement`
- `ImageElement`
- `ChartElement`
- `DiagramElement`
- `EquationElement`
- `CaptionElement`
- `FootnoteElement`
- `CodeElement`
- `PageHeaderElement`
- `PageFooterElement`

Common fields:

```python
class ElementBase(BaseModel):
    element_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    element_type: ElementType
    page_start: int
    page_end: int
    bounding_boxes: list[BoundingBox]
    reading_order: int
    section_id: UUID | None
    section_path: list[str]
    previous_element_id: UUID | None
    next_element_id: UUID | None
    nearby_element_ids: list[UUID]
    caption_element_id: UUID | None
    source_asset_id: UUID | None
    raw_content: str | None
    normalized_content: str | None
    parser_confidence: float | None
    ocr_confidence: float | None
    content_hash: str
    metadata: dict[str, JsonValue]
```

Bounding boxes are normalized to page coordinates and preserve original parser coordinates in metadata.

## Tables

A table must preserve:

- caption;
- column headers;
- row headers;
- merged-cell spans;
- cells with row and column positions;
- footnotes;
- raw parser representation;
- Markdown rendering;
- semantic summary;
- optional row chunks.

## Images, charts and diagrams

Preserve:

- original/cropped asset;
- caption;
- nearby context IDs;
- visual description;
- OCR text;
- chart-specific structured extraction when relevant;
- confidence and model provenance.

## Equations

Preserve:

- visual asset;
- parser text;
- LaTeX or MathML when available;
- variables and definitions;
- bounded contextual explanation;
- generated semantic description.

## Chunks

```python
class ChunkBase(BaseModel):
    chunk_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    parent_chunk_id: UUID | None
    modality: Modality
    chunk_type: ChunkType
    text: str
    token_count: int
    element_ids: list[UUID]
    page_start: int
    page_end: int
    section_path: list[str]
    source_object_keys: list[str]
    content_hash: str
    metadata: dict[str, JsonValue]
```

Parent chunks represent semantic sections or complete multimodal regions. Child chunks are retrieval units.

## Citations

```python
class Citation(BaseModel):
    citation_id: str
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    page_start: int
    page_end: int
    section_path: list[str]
    element_id: UUID | None
    chunk_id: UUID
    modality: Modality
    source_object_key: str
    evidence: str
```

Citation evidence must be derived from retrieved content and limited in size.
