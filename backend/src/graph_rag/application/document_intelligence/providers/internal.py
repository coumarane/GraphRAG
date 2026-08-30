"""Document Intelligence extraction chain: cheap tiers, then LLM, then vision.

Per field, cheapest-first: STRUCTURED_PARSER -> RULES -> TABLE_EXTRACTION,
first non-``None`` result wins. Whatever remains unresolved gets one batched
EMBEDDING_SEMANTIC pass across the whole document, then one batched LLM pass
over document text, then a per-page VISION pass (only when a chat model,
raw parser result, and document bytes are all available) -- each of the
three batched tiers narrows ``remaining`` further, cheapest first.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceExtractionRequest,
    DocumentIntelligenceExtractionResult,
    ExtractedFieldResult,
    ExtractionMethod,
    FieldType,
    ModelFieldSpec,
    confidence_band,
)
from graph_rag.application.ingestion.visual_enrichment import (
    collect_visual_targets,
    render_visual_png,
)
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.models import DocumentElement, TableElement
from graph_rag.domain.elements.table import TableCell, TableData
from graph_rag.domain.models.contracts import (
    ChatMessage,
    GenerationRequest,
    ImageBytesContentPart,
    MessageRole,
    ModelRole,
    TextContentPart,
)
from graph_rag.domain.models.protocols import ChatModel, EmbeddingModel
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.types import JsonValue
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

_RULES_ELEMENT_TYPES = frozenset(
    {
        ElementType.TEXT,
        ElementType.HEADING,
        ElementType.LIST,
        ElementType.CAPTION,
        ElementType.FOOTNOTE,
    }
)

_SCHEMA_FIELDS = frozenset({"title", "page_count", "language"})

MAX_EMBEDDING_CANDIDATES = 200
EMBEDDING_MATCH_FLOOR = 0.35
EMBEDDING_CONFIDENCE_CAP = 0.85

LLM_CONFIDENCE_CAP = 0.80
LLM_CONFIDENCE_DEFAULT = 0.65
LLM_UNGROUNDED_CAP = 0.55
LLM_CONTEXT_CHAR_BUDGET = 12_000

VISION_CONFIDENCE_CAP = 0.60
VISION_CONFIDENCE_DEFAULT = 0.45

_FIELD_JSON_CONTRACT = (
    "Respond with ONLY a JSON object of this exact shape (no markdown fences, no extra text):\n"
    '{"fields": {"<field_name>": {"value": <value-or-null>, "confidence": <0.0-1.0-or-null>, '
    '"source_text": "<verbatim quote-or-null>"}}}\n'
    "Use null for value when the field is not present or you are not confident. "
    "Never invent a value."
)
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

_DATE_CANDIDATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}"
)
# Day-first only, deliberately -- DD/MM vs MM/DD is genuinely ambiguous
# without locale context; picking one convention consistently beats guessing.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
    "%d %B %Y",
    "%d %b %Y",
)
_CURRENCY_RE = re.compile(
    r"[$€£]\s*([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP)\b",
    re.IGNORECASE,
)
_PERCENTAGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_BOOLEAN_TRUE = frozenset({"yes", "true", "y", "x", "pass", "passed", "compliant"})
_BOOLEAN_FALSE = frozenset({"no", "false", "n", "fail", "failed", "non-compliant", "noncompliant"})


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Normalized dot product; ``0.0`` on a zero vector to avoid division by zero."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _ordered_elements(document: NormalizedDocument) -> list[DocumentElement]:
    return sorted(
        document.elements, key=lambda element: (element.page_start, element.reading_order)
    )


def _ordered_tables(document: NormalizedDocument) -> list[TableElement]:
    return [element for element in _ordered_elements(document) if isinstance(element, TableElement)]


def _field_label_candidates(field: ModelFieldSpec) -> list[str]:
    candidates: list[str] = []
    if field.label:
        candidates.append(field.label)
    name_as_label = field.name.replace("_", " ")
    if name_as_label.lower() not in {c.lower() for c in candidates}:
        candidates.append(name_as_label)
    return candidates


def _parse_number(text: str, field_type: FieldType) -> int | float | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    cleaned = match.group(0).replace(",", "")
    try:
        if field_type == FieldType.INTEGER:
            return int(float(cleaned))
        return float(cleaned)
    except ValueError:
        return None


def _parse_boolean(text: str) -> bool | None:
    lowered = text.strip().strip(".").lower()
    if lowered in _BOOLEAN_TRUE:
        return True
    if lowered in _BOOLEAN_FALSE:
        return False
    return None


def _parse_date(text: str) -> str | None:
    match = _DATE_CANDIDATE_RE.search(text)
    if not match:
        return None
    candidate = match.group(0)
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        return parsed.date().isoformat()
    return None


def _parse_currency(text: str) -> float | None:
    match = _CURRENCY_RE.search(text)
    if not match:
        return None
    raw_number = match.group(1) or match.group(2)
    if raw_number is None:
        return None
    try:
        return float(raw_number.replace(",", ""))
    except ValueError:
        return None


def _parse_percentage(text: str) -> float | None:
    match = _PERCENTAGE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_list(text: str) -> list[JsonValue] | None:
    parts = re.split(r"[;,\n]", text)
    items: list[JsonValue] = [part.strip() for part in parts if part.strip()]
    return items or None


def _coerce_value(raw: str, field_type: FieldType) -> tuple[JsonValue, float] | None:
    """Validate/normalize a captured string against a field's declared shape.

    Returns ``(value, confidence)`` on a shape match, ``None`` otherwise --
    e.g. a DATE field whose capture isn't date-shaped is rejected here rather
    than fabricating a value.
    """
    text = raw.strip()
    if not text:
        return None
    if field_type in (FieldType.TABLE, FieldType.OBJECT):
        # TABLE is Tier 3's job; OBJECT needs an LLM to produce a nested
        # structure -- handled by _normalize_tiered_value in the LLM/Vision
        # tiers, never by this string-only coercion path.
        return None
    if field_type == FieldType.STRING:
        return (text, 0.60) if len(text) <= 300 else None
    if field_type in (FieldType.NUMBER, FieldType.INTEGER):
        number_value = _parse_number(text, field_type)
        return (number_value, 0.75) if number_value is not None else None
    if field_type == FieldType.BOOLEAN:
        bool_value = _parse_boolean(text)
        return (bool_value, 0.80) if bool_value is not None else None
    if field_type == FieldType.DATE:
        date_value = _parse_date(text)
        return (date_value, 0.70) if date_value is not None else None
    if field_type == FieldType.CURRENCY:
        currency_value = _parse_currency(text)
        return (currency_value, 0.80) if currency_value is not None else None
    if field_type == FieldType.PERCENTAGE:
        percentage_value = _parse_percentage(text)
        return (percentage_value, 0.80) if percentage_value is not None else None
    if field_type == FieldType.LIST:
        list_value = _parse_list(text)
        return (list_value, 0.65) if list_value is not None else None
    return None


def _structured_parser_tier(
    document: NormalizedDocument, field: ModelFieldSpec
) -> ExtractedFieldResult | None:
    if field.name in _SCHEMA_FIELDS:
        value = getattr(document, field.name)
        confidence = 0.97
    else:
        value = document.metadata.get(field.name)
        confidence = 0.75
    if value is None:
        return None
    return ExtractedFieldResult(
        name=field.name,
        value=value,
        confidence=confidence,
        confidence_band=confidence_band(confidence),
        extraction_method=ExtractionMethod.STRUCTURED_PARSER,
    )


def _rules_tier(document: NormalizedDocument, field: ModelFieldSpec) -> ExtractedFieldResult | None:
    if field.field_type in (FieldType.TABLE, FieldType.OBJECT):
        return None
    labels = [re.escape(candidate) for candidate in _field_label_candidates(field)]
    if not labels:
        return None
    pattern = re.compile(rf"(?im)^\s*(?:{'|'.join(labels)})\s*[:\-\u2013]\s*(.+)$")
    for element in _ordered_elements(document):
        if element.element_type not in _RULES_ELEMENT_TYPES:
            continue
        text = element.normalized_content or element.raw_content
        if not text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        coerced = _coerce_value(match.group(1), field.field_type)
        if coerced is None:
            continue
        value, confidence = coerced
        return ExtractedFieldResult(
            name=field.name,
            value=value,
            confidence=confidence,
            confidence_band=confidence_band(confidence),
            extraction_method=ExtractionMethod.RULES,
            page=element.page_start,
            source_text=match.group(0).strip(),
            bounding_box=element.bounding_boxes[0] if element.bounding_boxes else None,
        )
    return None


def _table_column_count(table: TableData) -> int:
    if table.column_headers:
        return len(table.column_headers)
    if not table.cells:
        return 0
    return max(cell.column_index for cell in table.cells) + 1


def _serialize_table(table: TableData) -> dict[str, JsonValue]:
    return {
        "column_headers": list(table.column_headers),
        "row_headers": list(table.row_headers),
        "cells": [
            {"row": cell.row_index, "column": cell.column_index, "text": cell.text}
            for cell in table.cells
        ],
    }


def _is_label_cell(cell: TableCell, lowered_labels: list[str], column_count: int) -> bool:
    if not (cell.is_row_header or cell.is_column_header) and column_count > 2:
        return False
    text = cell.text.strip().lower()
    if not text:
        return False
    return any(text == label or label in text for label in lowered_labels)


def _match_scalar_in_table(
    table_element: TableElement, field: ModelFieldSpec, lowered_labels: list[str]
) -> ExtractedFieldResult | None:
    table = table_element.table
    column_count = _table_column_count(table)
    for cell in table.cells:
        if not _is_label_cell(cell, lowered_labels, column_count):
            continue
        sibling = next(
            (
                c
                for c in table.cells
                if c.row_index == cell.row_index and c.column_index == cell.column_index + 1
            ),
            None,
        )
        if sibling is not None and sibling.text.strip():
            coerced = _coerce_value(sibling.text, field.field_type)
            if coerced is not None:
                value, _confidence = coerced
                return ExtractedFieldResult(
                    name=field.name,
                    value=value,
                    confidence=0.80,
                    confidence_band=confidence_band(0.80),
                    extraction_method=ExtractionMethod.TABLE_EXTRACTION,
                    page=table_element.page_start,
                    source_text=sibling.text.strip(),
                    bounding_box=table_element.bounding_boxes[0]
                    if table_element.bounding_boxes
                    else None,
                )
        data_rows = {c.row_index for c in table.cells if not c.is_column_header} - {cell.row_index}
        if len(data_rows) == 1:
            target_row = next(iter(data_rows))
            below = next(
                (
                    c
                    for c in table.cells
                    if c.row_index == target_row and c.column_index == cell.column_index
                ),
                None,
            )
            if below is not None and below.text.strip():
                coerced = _coerce_value(below.text, field.field_type)
                if coerced is not None:
                    value, _confidence = coerced
                    return ExtractedFieldResult(
                        name=field.name,
                        value=value,
                        confidence=0.65,
                        confidence_band=confidence_band(0.65),
                        extraction_method=ExtractionMethod.TABLE_EXTRACTION,
                        page=table_element.page_start,
                        source_text=below.text.strip(),
                        bounding_box=table_element.bounding_boxes[0]
                        if table_element.bounding_boxes
                        else None,
                    )
    return None


def _table_extraction_tier(
    document: NormalizedDocument,
    field: ModelFieldSpec,
    *,
    table_field_index: int,
    total_table_fields: int,
) -> ExtractedFieldResult | None:
    tables = _ordered_tables(document)
    if not tables:
        return None
    if field.field_type == FieldType.TABLE:
        if len(tables) == 1 and total_table_fields == 1:
            table_element = tables[0]
            confidence = 0.75
        else:
            if table_field_index < 0 or table_field_index >= len(tables):
                return None
            table_element = tables[table_field_index]
            confidence = 0.55
        table = table_element.table
        value: JsonValue = table.markdown or _serialize_table(table)
        return ExtractedFieldResult(
            name=field.name,
            value=value,
            confidence=confidence,
            confidence_band=confidence_band(confidence),
            extraction_method=ExtractionMethod.TABLE_EXTRACTION,
            page=table_element.page_start,
            bounding_box=table_element.bounding_boxes[0] if table_element.bounding_boxes else None,
        )
    labels = _field_label_candidates(field)
    lowered_labels = [label.strip().lower() for label in labels]
    if not lowered_labels:
        return None
    for table_element in tables:
        result = _match_scalar_in_table(table_element, field, lowered_labels)
        if result is not None:
            return result
    return None


def _candidate_spans(document: NormalizedDocument) -> list[tuple[str, DocumentElement]]:
    spans: list[tuple[str, Any]] = []
    for element in _ordered_elements(document):
        if len(spans) >= MAX_EMBEDDING_CANDIDATES:
            break
        if isinstance(element, TableElement):
            table = element.table
            for row_index in sorted({cell.row_index for cell in table.cells}):
                row_cells = sorted(
                    (cell for cell in table.cells if cell.row_index == row_index),
                    key=lambda cell: cell.column_index,
                )
                row_text = " | ".join(cell.text.strip() for cell in row_cells if cell.text.strip())
                if row_text:
                    spans.append((row_text, element))
        elif element.element_type in _RULES_ELEMENT_TYPES:
            text = element.normalized_content or element.raw_content
            if text and text.strip():
                spans.append((text.strip(), element))
    return spans[:MAX_EMBEDDING_CANDIDATES]


async def _embedding_semantic_tier(
    embedding_model: EmbeddingModel,
    document: NormalizedDocument,
    fields: list[ModelFieldSpec],
) -> dict[str, ExtractedFieldResult]:
    scalar_fields = [
        field for field in fields if field.field_type not in (FieldType.TABLE, FieldType.OBJECT)
    ]
    if not scalar_fields:
        return {}
    spans = _candidate_spans(document)
    if not spans:
        return {}
    span_texts = [text for text, _element in spans]
    query_texts = [f"{field.label} ({field.name})" for field in scalar_fields]
    span_vectors = await embedding_model.embed_documents(span_texts)
    query_vectors = await embedding_model.embed_documents(query_texts)

    found: dict[str, ExtractedFieldResult] = {}
    for field, query_vector in zip(scalar_fields, query_vectors, strict=True):
        best_score = -1.0
        best_index = -1
        for index, span_vector in enumerate(span_vectors):
            score = cosine_similarity(query_vector, span_vector)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index < 0 or best_score < EMBEDDING_MATCH_FLOOR:
            continue
        span_text, element = spans[best_index]
        coerced = _coerce_value(span_text, field.field_type)
        if coerced is None and field.field_type in (FieldType.STRING, FieldType.LIST):
            trimmed = span_text.strip()[:300]
            coerced = (trimmed, 0.0) if trimmed else None
        if coerced is None:
            continue
        value, _confidence = coerced
        scaled = (best_score - EMBEDDING_MATCH_FLOOR) / (1.0 - EMBEDDING_MATCH_FLOOR)
        confidence = min(EMBEDDING_CONFIDENCE_CAP, max(0.0, scaled) * EMBEDDING_CONFIDENCE_CAP)
        found[field.name] = ExtractedFieldResult(
            name=field.name,
            value=value,
            confidence=confidence,
            confidence_band=confidence_band(confidence),
            extraction_method=ExtractionMethod.EMBEDDING_SEMANTIC,
            page=element.page_start,
            source_text=span_text[:500],
            bounding_box=element.bounding_boxes[0] if element.bounding_boxes else None,
        )
    return found


def _document_text_excerpt(document: NormalizedDocument) -> str:
    parts: list[str] = []
    total = 0
    for element in _ordered_elements(document):
        text = (
            element.table.markdown
            if isinstance(element, TableElement)
            else (element.normalized_content or element.raw_content)
        )
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= LLM_CONTEXT_CHAR_BUDGET:
            break
    return "\n".join(parts)[:LLM_CONTEXT_CHAR_BUDGET]


def _field_spec_lines(fields: list[ModelFieldSpec]) -> str:
    return "\n".join(
        f"- {field.name} ({field.label}, type={field.field_type.value})" for field in fields
    )


def _system_prompt() -> str:
    return (
        "You extract structured field values from a document. Only use information "
        "present in the provided content. Never invent or guess a value -- return "
        "null when a field is not present or you are not confident."
    )


def _user_prompt(fields: list[ModelFieldSpec], context_label: str, context: str) -> str:
    return (
        f"Fields to extract:\n{_field_spec_lines(fields)}\n\n"
        f"{context_label}:\n{context}\n\n"
        f"{_FIELD_JSON_CONTRACT}"
    )


def _parse_field_json(text: str) -> dict[str, Any]:
    """Forgiving JSON extraction, mirroring ``local_pipeline.py::_parse_vision_json``.

    Written fresh here rather than imported -- that function is private to
    ``local_pipeline.py``, not meant for cross-module reuse (same reasoning
    that led the embedding tier to write its own ``cosine_similarity`` rather
    than import ``qdrant/memory.py``'s private ``_dot``).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload: Any = None
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(cleaned)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None
    if not isinstance(payload, dict):
        return {}
    fields = payload.get("fields")
    return fields if isinstance(fields, dict) else payload


def _entry_parts(entry: Any) -> tuple[Any, Any, Any]:
    """Split one field's JSON entry into (value, confidence, source_text).

    Tolerates a bare scalar in place of the ``{value, confidence, source_text}``
    object -- some models drop the wrapper when they're very confident.
    """
    if isinstance(entry, dict):
        return entry.get("value"), entry.get("confidence"), entry.get("source_text")
    return entry, None, None


def _resolve_confidence(reported: Any, *, cap: float, default: float) -> float:
    if (
        isinstance(reported, int | float)
        and not isinstance(reported, bool)
        and 0.0 <= reported <= 1.0
    ):
        return min(float(reported), cap)
    return default


def _normalize_tiered_value(value: Any, field_type: FieldType) -> JsonValue | None:
    """Accept native JSON types matching ``field_type`` directly; otherwise
    stringify and reuse ``_coerce_value``'s regex validators.

    Never fabricates a value that doesn't shape-match -- mirrors
    ``_coerce_value``'s own contract, just starting from a JSON value instead
    of a captured string.
    """
    if field_type == FieldType.TABLE:
        return None
    if field_type == FieldType.OBJECT:
        return value if isinstance(value, dict) else None
    if field_type == FieldType.LIST:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            coerced = _coerce_value(value, field_type)
            return coerced[0] if coerced else None
        return None
    if field_type in (FieldType.NUMBER, FieldType.INTEGER):
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return int(value) if field_type == FieldType.INTEGER else float(value)
        if isinstance(value, str):
            coerced = _coerce_value(value, field_type)
            return coerced[0] if coerced else None
        return None
    if field_type == FieldType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            coerced = _coerce_value(value, field_type)
            return coerced[0] if coerced else None
        return None
    if field_type == FieldType.STRING:
        if isinstance(value, str):
            return value[:300]
        return None
    # DATE, CURRENCY, PERCENTAGE -- inherently text-shaped.
    if isinstance(value, str):
        coerced = _coerce_value(value, field_type)
        return coerced[0] if coerced else None
    return None


async def _llm_tier(
    chat_model: ChatModel,
    document: NormalizedDocument,
    fields: list[ModelFieldSpec],
) -> dict[str, ExtractedFieldResult]:
    scalar_fields = [field for field in fields if field.field_type != FieldType.TABLE]
    if not scalar_fields:
        return {}
    excerpt = _document_text_excerpt(document)
    if not excerpt:
        return {}
    lowered_excerpt = excerpt.lower()

    response = await chat_model.generate(
        GenerationRequest(
            messages=[
                ChatMessage(role=MessageRole.SYSTEM, content=_system_prompt()),
                ChatMessage(
                    role=MessageRole.USER,
                    content=_user_prompt(scalar_fields, "Document text", excerpt),
                ),
            ],
            role=ModelRole.TEXT,
            temperature=0.0,
            prompt_version="document-intelligence-llm-tier-v1",
        )
    )
    payload = _parse_field_json(response.text)

    found: dict[str, ExtractedFieldResult] = {}
    for field in scalar_fields:
        entry = payload.get(field.name)
        if entry is None:
            continue
        raw_value, reported_confidence, source_text = _entry_parts(entry)
        if raw_value is None:
            continue
        value = _normalize_tiered_value(raw_value, field.field_type)
        if value is None:
            continue
        confidence = _resolve_confidence(
            reported_confidence, cap=LLM_CONFIDENCE_CAP, default=LLM_CONFIDENCE_DEFAULT
        )
        grounded_source: str | None = None
        if isinstance(source_text, str) and source_text.strip():
            grounded_source = source_text.strip()
            if grounded_source.lower() not in lowered_excerpt:
                confidence = min(confidence, LLM_UNGROUNDED_CAP)
        found[field.name] = ExtractedFieldResult(
            name=field.name,
            value=value,
            confidence=confidence,
            confidence_band=confidence_band(confidence),
            extraction_method=ExtractionMethod.LLM,
            source_text=grounded_source,
        )
    return found


async def _vision_tier(
    chat_model: ChatModel,
    document_bytes: bytes,
    raw_parser_result: RawParserResult,
    fields: list[ModelFieldSpec],
    *,
    vision_max_pages: int,
) -> dict[str, ExtractedFieldResult]:
    scalar_fields = [field for field in fields if field.field_type != FieldType.TABLE]
    if not scalar_fields:
        return {}
    vision_targets = [
        target for target in collect_visual_targets(raw_parser_result) if target.tool == "vision"
    ]
    if not vision_targets:
        return {}

    # Dedupe by page (not by target, unlike _vision_enrich_pages) since this
    # tier batches all remaining fields into one call per page.
    page_numbers: list[int] = []
    for target in vision_targets:
        if target.page_number not in page_numbers:
            page_numbers.append(target.page_number)
    if vision_max_pages > 0:
        page_numbers = page_numbers[:vision_max_pages]

    found: dict[str, ExtractedFieldResult] = {}
    remaining = list(scalar_fields)
    for page_number in page_numbers:
        if not remaining:
            break
        try:
            png = await asyncio.to_thread(render_visual_png, document_bytes, page_number, None)
            response = await chat_model.generate(
                GenerationRequest(
                    messages=[
                        ChatMessage(role=MessageRole.SYSTEM, content=_system_prompt()),
                        ChatMessage(
                            role=MessageRole.USER,
                            content=[
                                TextContentPart(
                                    text=_user_prompt(
                                        remaining, "This page image", "(see attached image)"
                                    )
                                ),
                                ImageBytesContentPart(data=png, mime_type="image/png"),
                            ],
                        ),
                    ],
                    role=ModelRole.VISION,
                    temperature=0.0,
                    prompt_version="document-intelligence-vision-tier-v1",
                )
            )
            payload = _parse_field_json(response.text)
        except Exception:
            logger.warning(
                "document_intelligence_vision_tier_page_failed", page=page_number, exc_info=True
            )
            continue

        for field in list(remaining):
            entry = payload.get(field.name)
            if entry is None:
                continue
            raw_value, reported_confidence, source_text = _entry_parts(entry)
            if raw_value is None:
                continue
            value = _normalize_tiered_value(raw_value, field.field_type)
            if value is None:
                continue
            confidence = _resolve_confidence(
                reported_confidence, cap=VISION_CONFIDENCE_CAP, default=VISION_CONFIDENCE_DEFAULT
            )
            found[field.name] = ExtractedFieldResult(
                name=field.name,
                value=value,
                confidence=confidence,
                confidence_band=confidence_band(confidence),
                extraction_method=ExtractionMethod.VISION,
                page=page_number,
                source_text=source_text.strip() if isinstance(source_text, str) else None,
            )
            remaining.remove(field)
    return found


INTERNAL_PROVIDER_VERSION = "0.5.0"


class InternalExtractionProvider:
    """Document Intelligence extraction chain: cheap tiers, then LLM, then vision.

    Distinct from -- and unrelated to -- ``application.plugins
    .document_intelligence._InternalProvider``, which is a dead Phase-1
    plugin-registry placeholder that nothing calls.
    """

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        chat_model: ChatModel | None = None,
        *,
        enable_llm_tier: bool = True,
        enable_vision_tier: bool = True,
        vision_max_pages: int = 0,
    ) -> None:
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self._enable_llm_tier = enable_llm_tier
        self._enable_vision_tier = enable_vision_tier
        self._vision_max_pages = vision_max_pages

    async def extract(
        self, request: DocumentIntelligenceExtractionRequest
    ) -> DocumentIntelligenceExtractionResult:
        document = request.document
        table_field_names = [
            field.name for field in request.fields if field.field_type == FieldType.TABLE
        ]
        found: dict[str, ExtractedFieldResult] = {}

        for field in request.fields:
            result: ExtractedFieldResult | None = None
            try:
                result = _structured_parser_tier(document, field)
                if result is None:
                    result = _rules_tier(document, field)
                if result is None:
                    table_index = (
                        table_field_names.index(field.name)
                        if field.name in table_field_names
                        else -1
                    )
                    result = _table_extraction_tier(
                        document,
                        field,
                        table_field_index=table_index,
                        total_table_fields=len(table_field_names),
                    )
            except Exception:
                logger.warning(
                    "document_intelligence_field_tier_failed", field=field.name, exc_info=True
                )
                result = None
            if result is not None:
                if request.model_name:
                    result = result.model_copy(update={"model_name": request.model_name})
                found[field.name] = result

        remaining = [field for field in request.fields if field.name not in found]
        if remaining:
            try:
                embedded = await _embedding_semantic_tier(
                    self._embedding_model, document, remaining
                )
            except Exception:
                logger.warning("document_intelligence_embedding_tier_failed", exc_info=True)
                embedded = {}
            for name, result in embedded.items():
                if request.model_name:
                    result = result.model_copy(update={"model_name": request.model_name})
                found[name] = result

        remaining = [field for field in request.fields if field.name not in found]
        if remaining and self._chat_model is not None and self._enable_llm_tier:
            try:
                llm_found = await _llm_tier(self._chat_model, document, remaining)
            except Exception:
                logger.warning("document_intelligence_llm_tier_failed", exc_info=True)
                llm_found = {}
            for name, result in llm_found.items():
                if request.model_name:
                    result = result.model_copy(update={"model_name": request.model_name})
                found[name] = result

        remaining = [field for field in request.fields if field.name not in found]
        if (
            remaining
            and self._chat_model is not None
            and self._enable_vision_tier
            and request.raw_parser_result is not None
            and request.document_bytes is not None
        ):
            try:
                vision_found = await _vision_tier(
                    self._chat_model,
                    request.document_bytes,
                    request.raw_parser_result,
                    remaining,
                    vision_max_pages=self._vision_max_pages,
                )
            except Exception:
                logger.warning("document_intelligence_vision_tier_failed", exc_info=True)
                vision_found = {}
            for name, result in vision_found.items():
                if request.model_name:
                    result = result.model_copy(update={"model_name": request.model_name})
                found[name] = result

        ordered = [found[field.name] for field in request.fields if field.name in found]
        return DocumentIntelligenceExtractionResult(
            fields=ordered,
            requested_field_names=[field.name for field in request.fields],
            unresolved_field_names=[
                field.name for field in request.fields if field.name not in found
            ],
        )
