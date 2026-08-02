"""Build structural document graphs from normalized documents and chunks."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.models import CaptionElement
from enterprise_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from enterprise_rag.domain.graph.vocabulary import StructuralNodeLabel, StructuralRelationshipType
from enterprise_rag.domain.ids import deterministic_id
from enterprise_rag.domain.types import JsonValue

_ELEMENT_LABELS: dict[ElementType, StructuralNodeLabel] = {
    ElementType.TEXT: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.HEADING: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.LIST: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.CODE: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.FOOTNOTE: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.PAGE_HEADER: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.PAGE_FOOTER: StructuralNodeLabel.TEXT_ELEMENT,
    ElementType.IMAGE: StructuralNodeLabel.IMAGE,
    ElementType.CHART: StructuralNodeLabel.CHART,
    ElementType.DIAGRAM: StructuralNodeLabel.DIAGRAM,
    ElementType.TABLE: StructuralNodeLabel.TABLE,
    ElementType.EQUATION: StructuralNodeLabel.EQUATION,
    ElementType.CAPTION: StructuralNodeLabel.CAPTION,
}


class StructuralGraphBuilder:
    """Project document structure into allowlisted graph nodes/edges."""

    def build(
        self,
        document: NormalizedDocument,
        chunks: ChunkingResult | None = None,
    ) -> ProjectedGraph:
        nodes: list[GraphNode] = []
        relationships: list[GraphRelationship] = []
        tenant_id = document.tenant_id

        tenant_node = self._node(
            tenant_id,
            StructuralNodeLabel.TENANT,
            document.tenant_id,
            {"tenant_id": str(tenant_id)},
        )
        document_node = self._node(
            tenant_id,
            StructuralNodeLabel.DOCUMENT,
            document.document_id,
            {
                "document_id": str(document.document_id),
                "title": document.title,
                "source_filename": document.source_filename,
                "mime_type": document.mime_type,
            },
        )
        version_node = self._node(
            tenant_id,
            StructuralNodeLabel.DOCUMENT_VERSION,
            document.version_id,
            {
                "version_id": str(document.version_id),
                "document_id": str(document.document_id),
                "language": document.language,
                "parser": document.parser_info.parser_name,
            },
        )
        nodes.extend([tenant_node, document_node, version_node])
        relationships.append(
            self._rel(
                tenant_id,
                StructuralRelationshipType.HAS_VERSION,
                document_node.node_id,
                version_node.node_id,
            )
        )

        page_nodes: dict[int, GraphNode] = {}
        for page in document.pages:
            page_node = self._node(
                tenant_id,
                StructuralNodeLabel.PAGE,
                page.page_id,
                {
                    "page_number": page.page_number,
                    "width": page.width,
                    "height": page.height,
                },
            )
            page_nodes[page.page_number] = page_node
            nodes.append(page_node)
            relationships.append(
                self._rel(
                    tenant_id,
                    StructuralRelationshipType.HAS_PAGE,
                    version_node.node_id,
                    page_node.node_id,
                )
            )

        section_nodes: dict[tuple[str, ...], GraphNode] = {}
        for section in document.sections:
            key = tuple(section.path) if section.path else (section.title or "section",)
            section_node = self._node(
                tenant_id,
                StructuralNodeLabel.SECTION,
                section.section_id,
                {
                    "title": section.title,
                    "level": section.level,
                    "path": list(section.path),
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                },
            )
            section_nodes[key] = section_node
            nodes.append(section_node)
            relationships.append(
                self._rel(
                    tenant_id,
                    StructuralRelationshipType.HAS_SECTION,
                    version_node.node_id,
                    section_node.node_id,
                )
            )

        element_nodes: dict[UUID, GraphNode] = {}
        ordered_elements = sorted(
            document.elements,
            key=lambda item: (item.page_start, item.reading_order),
        )
        for element in ordered_elements:
            label = _ELEMENT_LABELS.get(element.element_type, StructuralNodeLabel.TEXT_ELEMENT)
            element_node = self._node(
                tenant_id,
                label,
                element.element_id,
                {
                    "element_id": str(element.element_id),
                    "element_type": element.element_type.value,
                    "page_start": element.page_start,
                    "page_end": element.page_end,
                    "section_path": list(element.section_path),
                    "content_hash": element.content_hash,
                },
            )
            element_nodes[element.element_id] = element_node
            nodes.append(element_node)
            relationships.append(
                self._rel(
                    tenant_id,
                    StructuralRelationshipType.HAS_ELEMENT,
                    version_node.node_id,
                    element_node.node_id,
                )
            )
            section_key = tuple(element.section_path) if element.section_path else None
            if section_key and section_key in section_nodes:
                relationships.append(
                    self._rel(
                        tenant_id,
                        StructuralRelationshipType.HAS_ELEMENT,
                        section_nodes[section_key].node_id,
                        element_node.node_id,
                        properties={"via": "section"},
                    )
                )
            linked_page = page_nodes.get(element.page_start)
            if linked_page is not None:
                relationships.append(
                    self._rel(
                        tenant_id,
                        StructuralRelationshipType.APPEARS_ON,
                        element_node.node_id,
                        linked_page.node_id,
                    )
                )

        for index, element in enumerate(ordered_elements):
            current = element_nodes[element.element_id]
            if index + 1 < len(ordered_elements):
                nxt = element_nodes[ordered_elements[index + 1].element_id]
                relationships.append(
                    self._rel(
                        tenant_id,
                        StructuralRelationshipType.NEXT_ELEMENT,
                        current.node_id,
                        nxt.node_id,
                    )
                )
                relationships.append(
                    self._rel(
                        tenant_id,
                        StructuralRelationshipType.PREVIOUS_ELEMENT,
                        nxt.node_id,
                        current.node_id,
                    )
                )
            if isinstance(element, CaptionElement) and element.target_element_id:
                target = element_nodes.get(element.target_element_id)
                if target is not None:
                    relationships.append(
                        self._rel(
                            tenant_id,
                            StructuralRelationshipType.HAS_CAPTION,
                            target.node_id,
                            current.node_id,
                        )
                    )

        if chunks is not None:
            for chunk in chunks.all_chunks:
                nodes.append(self._chunk_node(tenant_id, chunk))
                relationships.append(
                    self._rel(
                        tenant_id,
                        StructuralRelationshipType.HAS_CHUNK,
                        version_node.node_id,
                        chunk.chunk_id,
                    )
                )
                for element_id in chunk.element_ids:
                    if element_id in element_nodes:
                        relationships.append(
                            self._rel(
                                tenant_id,
                                StructuralRelationshipType.DERIVED_FROM,
                                chunk.chunk_id,
                                element_id,
                            )
                        )
                if chunk.chunk_type is ChunkType.TABLE_ROW:
                    for element_id in chunk.element_ids:
                        if element_id in element_nodes:
                            relationships.append(
                                self._rel(
                                    tenant_id,
                                    StructuralRelationshipType.HAS_ROW,
                                    element_id,
                                    chunk.chunk_id,
                                    properties={"chunk_type": chunk.chunk_type.value},
                                )
                            )

        return ProjectedGraph(
            tenant_id=tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            nodes=nodes,
            relationships=relationships,
        )

    def _chunk_node(self, tenant_id: UUID, chunk: ChunkBase) -> GraphNode:
        return self._node(
            tenant_id,
            StructuralNodeLabel.CHUNK,
            chunk.chunk_id,
            {
                "chunk_id": str(chunk.chunk_id),
                "chunk_type": chunk.chunk_type.value,
                "modality": chunk.modality.value,
                "document_id": str(chunk.document_id),
                "version_id": str(chunk.version_id),
                "parent_chunk_id": (
                    str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None
                ),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_path": list(chunk.section_path),
                "content_hash": chunk.content_hash,
                "token_count": chunk.token_count,
            },
        )

    def _node(
        self,
        tenant_id: UUID,
        label: StructuralNodeLabel,
        node_id: UUID,
        properties: dict[str, JsonValue],
    ) -> GraphNode:
        return GraphNode(
            node_id=node_id,
            label=label.value,
            tenant_id=tenant_id,
            properties=properties,
        )

    def _rel(
        self,
        tenant_id: UUID,
        relationship_type: StructuralRelationshipType,
        source_node_id: UUID,
        target_node_id: UUID,
        properties: dict[str, JsonValue] | None = None,
    ) -> GraphRelationship:
        rel_id = deterministic_id(
            str(tenant_id),
            relationship_type.value,
            str(source_node_id),
            str(target_node_id),
        )
        return GraphRelationship(
            relationship_id=rel_id,
            relationship_type=relationship_type.value,
            tenant_id=tenant_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            properties=properties or {},
        )
