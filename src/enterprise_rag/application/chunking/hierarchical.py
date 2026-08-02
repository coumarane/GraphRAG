"""Hierarchical multimodal chunking from normalized documents."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from enterprise_rag.config.settings import ChunkingSettings
from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.models import (
    CaptionElement,
    ChartElement,
    DocumentElement,
    EquationElement,
    ImageElement,
    TableElement,
)
from enterprise_rag.domain.ids import content_sha256_hex, deterministic_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.types import JsonValue

_SKIP = {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}
_TEXTISH = {
    ElementType.TEXT,
    ElementType.HEADING,
    ElementType.LIST,
    ElementType.CODE,
    ElementType.FOOTNOTE,
}


@dataclass
class _TextBuffer:
    elements: list[DocumentElement]
    texts: list[str]

    def clear(self) -> None:
        self.elements.clear()
        self.texts.clear()

    @property
    def token_estimate(self) -> int:
        return _estimate_tokens("\n\n".join(self.texts))


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _element_text(element: DocumentElement) -> str:
    if isinstance(element, TableElement):
        return (
            element.table.semantic_summary
            or element.table.markdown
            or element.normalized_content
            or element.raw_content
            or ""
        )
    if isinstance(element, ImageElement):
        parts = [
            element.visual_description,
            element.ocr_text,
            element.normalized_content,
            element.raw_content,
        ]
        return " | ".join(part for part in parts if part) or "[image]"
    if isinstance(element, ChartElement):
        parts = [
            element.title,
            element.visual_description,
            element.normalized_content,
            element.raw_content,
        ]
        return " | ".join(part for part in parts if part) or "[chart]"
    if isinstance(element, EquationElement):
        parts = [
            element.semantic_description,
            element.contextual_explanation,
            element.latex,
            element.normalized_content,
            element.raw_content,
        ]
        return " | ".join(part for part in parts if part) or "[equation]"
    return element.normalized_content or element.raw_content or ""


def _modality_for(element: DocumentElement) -> Modality:
    mapping = {
        ElementType.TEXT: Modality.TEXT,
        ElementType.HEADING: Modality.TEXT,
        ElementType.LIST: Modality.TEXT,
        ElementType.CODE: Modality.TEXT,
        ElementType.FOOTNOTE: Modality.TEXT,
        ElementType.CAPTION: Modality.TEXT,
        ElementType.IMAGE: Modality.IMAGE,
        ElementType.CHART: Modality.CHART,
        ElementType.DIAGRAM: Modality.DIAGRAM,
        ElementType.TABLE: Modality.TABLE,
        ElementType.EQUATION: Modality.EQUATION,
    }
    return mapping.get(element.element_type, Modality.TEXT)


def _chunk_type_for(element: DocumentElement) -> ChunkType:
    mapping = {
        ElementType.IMAGE: ChunkType.IMAGE,
        ElementType.CHART: ChunkType.CHART,
        ElementType.DIAGRAM: ChunkType.IMAGE,
        ElementType.TABLE: ChunkType.TABLE,
        ElementType.EQUATION: ChunkType.EQUATION,
    }
    return mapping.get(element.element_type, ChunkType.TEXT)


class HierarchicalMultimodalChunker:
    """Build parent/child multimodal chunks from a normalized document."""

    def __init__(self, settings: ChunkingSettings | None = None) -> None:
        self._settings = settings or ChunkingSettings()

    def chunk(self, document: NormalizedDocument) -> ChunkingResult:
        parents: list[ChunkBase] = []
        children: list[ChunkBase] = []

        by_section: dict[tuple[str, ...], list[DocumentElement]] = defaultdict(list)
        for element in document.elements:
            if element.element_type in _SKIP:
                continue
            key = tuple(element.section_path) if element.section_path else ("(document)",)
            by_section[key].append(element)

        for section_path, elements in by_section.items():
            ordered = sorted(elements, key=lambda item: (item.page_start, item.reading_order))
            parent = self._make_section_parent(document, list(section_path), ordered)
            parents.append(parent)
            children.extend(self._chunk_section(document, parent, ordered))

        return ChunkingResult(parents=parents, children=children)

    def _make_section_parent(
        self,
        document: NormalizedDocument,
        section_path: list[str],
        elements: list[DocumentElement],
    ) -> ChunkBase:
        texts = [_element_text(el) for el in elements if _element_text(el)]
        joined = "\n\n".join(texts)
        # Bound parent text roughly to parent_target_tokens.
        max_chars = self._settings.parent_target_tokens * 4
        if len(joined) > max_chars:
            joined = joined[:max_chars].rstrip() + "…"
        content_hash = content_sha256_hex(f"section|{section_path}|{joined}")
        chunk_id = deterministic_id(
            str(document.tenant_id),
            str(document.document_id),
            str(document.version_id),
            f"parent:{'/'.join(section_path)}:{content_hash[:16]}",
        )
        return ChunkBase(
            chunk_id=chunk_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            parent_chunk_id=None,
            modality=Modality.TEXT,
            chunk_type=ChunkType.SECTION,
            text=joined or " / ".join(section_path) or document.title or document.source_filename,
            token_count=_estimate_tokens(joined),
            element_ids=[el.element_id for el in elements],
            page_start=min(el.page_start for el in elements),
            page_end=max(el.page_end for el in elements),
            section_path=section_path,
            source_object_keys=[],
            content_hash=content_hash,
            metadata={"role": "parent"},
        )

    def _chunk_section(
        self,
        document: NormalizedDocument,
        parent: ChunkBase,
        elements: list[DocumentElement],
    ) -> list[ChunkBase]:
        children: list[ChunkBase] = []
        buffer = _TextBuffer(elements=[], texts=[])
        index = 0
        while index < len(elements):
            element = elements[index]
            if element.element_type in _TEXTISH:
                text = _element_text(element)
                if not text:
                    index += 1
                    continue
                tentative = _estimate_tokens("\n\n".join([*buffer.texts, text]))
                if buffer.texts and tentative > self._settings.child_target_tokens:
                    overlap_text = buffer.texts[-1] if buffer.texts else ""
                    children.append(self._flush_text_child(document, parent, buffer))
                    buffer.clear()
                    if (
                        self._settings.overlap_tokens > 0
                        and overlap_text
                        and _estimate_tokens(overlap_text) <= self._settings.overlap_tokens
                    ):
                        buffer.texts.append(overlap_text)
                    buffer.elements.append(element)
                    buffer.texts.append(text)
                    index += 1
                    continue
                buffer.elements.append(element)
                buffer.texts.append(text)
                index += 1
                continue

            if buffer.texts:
                children.append(self._flush_text_child(document, parent, buffer))
                buffer.clear()

            if element.element_type is ElementType.TABLE:
                children.extend(self._table_chunks(document, parent, element))
                index += 1
                continue

            if element.element_type is ElementType.EQUATION:
                explanation = None
                if (
                    self._settings.preserve_equations
                    and index + 1 < len(elements)
                    and elements[index + 1].element_type in _TEXTISH
                ):
                    explanation = elements[index + 1]
                    index += 1
                children.append(
                    self._atomic_chunk(
                        document,
                        parent,
                        element,
                        extra_elements=[explanation] if explanation else [],
                    )
                )
                index += 1
                continue

            if element.element_type in {
                ElementType.IMAGE,
                ElementType.CHART,
                ElementType.DIAGRAM,
            }:
                if not self._settings.generate_image_chunks:
                    index += 1
                    continue
                caption = self._find_caption(elements, element)
                context_bits: list[DocumentElement] = []
                if caption:
                    context_bits.append(caption)
                if self._settings.preserve_figure_context and index > 0:
                    prev = elements[index - 1]
                    if prev.element_type in _TEXTISH:
                        context_bits.insert(0, prev)
                children.append(
                    self._atomic_chunk(document, parent, element, extra_elements=context_bits)
                )
                if self._settings.generate_composite_chunks and context_bits:
                    children.append(
                        self._composite_chunk(document, parent, element, context_bits)
                    )
                index += 1
                continue

            if element.element_type is ElementType.CAPTION:
                index += 1
                continue

            # Fallback: treat as text.
            text = _element_text(element)
            if text:
                buffer.elements.append(element)
                buffer.texts.append(text)
            index += 1

        if buffer.texts:
            children.append(self._flush_text_child(document, parent, buffer))
        return children

    def _flush_text_child(
        self,
        document: NormalizedDocument,
        parent: ChunkBase,
        buffer: _TextBuffer,
    ) -> ChunkBase:
        text = "\n\n".join(buffer.texts)
        return self._build_chunk(
            document=document,
            parent=parent,
            text=text,
            elements=list(buffer.elements),
            modality=Modality.TEXT,
            chunk_type=ChunkType.TEXT,
        )

    def _atomic_chunk(
        self,
        document: NormalizedDocument,
        parent: ChunkBase,
        element: DocumentElement,
        *,
        extra_elements: list[DocumentElement],
    ) -> ChunkBase:
        parts = [_element_text(element)]
        for extra in extra_elements:
            extra_text = _element_text(extra)
            if extra_text:
                parts.append(extra_text)
        text = "\n\n".join(part for part in parts if part)
        return self._build_chunk(
            document=document,
            parent=parent,
            text=text,
            elements=[element, *extra_elements],
            modality=_modality_for(element),
            chunk_type=_chunk_type_for(element),
        )

    def _composite_chunk(
        self,
        document: NormalizedDocument,
        parent: ChunkBase,
        element: DocumentElement,
        context_bits: list[DocumentElement],
    ) -> ChunkBase:
        parts = [_element_text(el) for el in [element, *context_bits]]
        text = "\n\n".join(part for part in parts if part)
        keys = []
        if element.source_asset_id:
            keys.append(str(element.source_asset_id))
        return self._build_chunk(
            document=document,
            parent=parent,
            text=text,
            elements=[element, *context_bits],
            modality=Modality.COMPOSITE,
            chunk_type=ChunkType.MULTIMODAL_COMPOSITE,
            source_object_keys=keys,
            metadata={"composite_of": element.element_type.value},
        )

    def _table_chunks(
        self,
        document: NormalizedDocument,
        parent: ChunkBase,
        element: TableElement,
    ) -> list[ChunkBase]:
        chunks = [
            self._build_chunk(
                document=document,
                parent=parent,
                text=_element_text(element),
                elements=[element],
                modality=Modality.TABLE,
                chunk_type=ChunkType.TABLE,
            )
        ]
        if not self._settings.generate_table_row_chunks:
            return chunks
        if not element.table.cells:
            return chunks

        rows: dict[int, list[str]] = defaultdict(list)
        for cell in element.table.cells:
            rows[cell.row_index].append(cell.text)
        headers = element.table.column_headers
        for row_index, values in sorted(rows.items()):
            if headers and len(headers) == len(values):
                row_text = " | ".join(f"{h}: {v}" for h, v in zip(headers, values, strict=False))
            else:
                row_text = " | ".join(values)
            if not row_text.strip():
                continue
            chunks.append(
                self._build_chunk(
                    document=document,
                    parent=parent,
                    text=row_text,
                    elements=[element],
                    modality=Modality.TABLE,
                    chunk_type=ChunkType.TABLE_ROW,
                    metadata={"row_index": row_index},
                    salt=f"row:{row_index}",
                )
            )
        return chunks

    def _find_caption(
        self,
        elements: list[DocumentElement],
        target: DocumentElement,
    ) -> CaptionElement | None:
        for item in elements:
            if isinstance(item, CaptionElement) and item.target_element_id == target.element_id:
                return item
        return None

    def _build_chunk(
        self,
        *,
        document: NormalizedDocument,
        parent: ChunkBase,
        text: str,
        elements: list[DocumentElement],
        modality: Modality,
        chunk_type: ChunkType,
        source_object_keys: list[str] | None = None,
        metadata: dict[str, JsonValue] | None = None,
        salt: str = "",
    ) -> ChunkBase:
        content_hash = content_sha256_hex(
            f"{chunk_type.value}|{parent.chunk_id}|{salt}|{text}"
        )
        chunk_id = deterministic_id(
            str(document.tenant_id),
            str(document.document_id),
            str(document.version_id),
            f"child:{chunk_type.value}:{content_hash[:16]}",
        )
        page_start = min((el.page_start for el in elements), default=parent.page_start)
        page_end = max((el.page_end for el in elements), default=parent.page_end)
        section_path = elements[0].section_path if elements else parent.section_path
        meta: dict[str, JsonValue] = {"role": "child", **(metadata or {})}
        return ChunkBase(
            chunk_id=chunk_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            parent_chunk_id=parent.chunk_id,
            modality=modality,
            chunk_type=chunk_type,
            text=text,
            token_count=_estimate_tokens(text),
            element_ids=[el.element_id for el in elements],
            page_start=page_start,
            page_end=page_end,
            section_path=list(section_path),
            source_object_keys=source_object_keys or [],
            content_hash=content_hash,
            metadata=meta,
        )
