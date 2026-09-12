"""Extract page renders, figure crops, and table JSON into parse-attempt assets."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from graph_rag.application.ingestion.canonical_store import CanonicalStore
from graph_rag.application.ingestion.visual_enrichment import render_visual_png
from graph_rag.domain.documents.components import DocumentAsset
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.geometry import BoundingBox
from graph_rag.domain.elements.models import DocumentElement, TableElement
from graph_rag.domain.ids import content_sha256_hex, deterministic_id
from graph_rag.domain.storage.object_keys import (
    parse_figure_asset_key,
    parse_page_render_key,
    parse_table_asset_key,
)
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

_FIGURE_TYPES = {ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM}


async def extract_canonical_assets(
    *,
    object_store: ObjectStore,
    tenant: TenantContext,
    document: NormalizedDocument,
    original_bytes: bytes | None,
    mime_type: str,
    filename: str,
    attempt_id: UUID,
) -> tuple[NormalizedDocument, list[str]]:
    """Write binaries/table JSON, set ``source_asset_id``, and rewrite shards."""
    warnings: list[str] = []
    is_pdf = _is_pdf(mime_type, filename)
    if not is_pdf:
        warnings.append("page_renders_skipped:not_pdf")

    assets_by_id = {asset.asset_id: asset for asset in document.assets}
    updated_elements: list[DocumentElement] = []

    if is_pdf and original_bytes:
        page_numbers = sorted({page.page_number for page in document.pages})
        if not page_numbers and document.page_count:
            page_numbers = list(range(1, document.page_count + 1))
        for page_number in page_numbers:
            asset_id = deterministic_id(
                "canonical_page_render",
                str(document.version_id),
                f"{page_number:04d}",
            )
            object_key = parse_page_render_key(
                tenant_id=tenant.tenant_id,
                document_id=document.document_id,
                version_id=document.version_id,
                attempt_id=attempt_id,
                page_number=page_number,
            )
            try:
                png = await asyncio.to_thread(render_visual_png, original_bytes, page_number, None)
            except Exception as exc:
                warnings.append(f"page_render_failed:{page_number}:{type(exc).__name__}")
                logger.warning(
                    "canonical_page_render_failed",
                    page_number=page_number,
                    error=str(exc),
                )
                continue
            stored = await _put_asset(object_store, tenant, object_key, png, "image/png")
            assets_by_id[asset_id] = DocumentAsset(
                asset_id=asset_id,
                asset_type="page_render",
                mime_type="image/png",
                object_key=object_key,
                page_number=page_number,
                content_hash=stored[0],
                byte_size=stored[1],
            )
    elif is_pdf:
        warnings.append("page_renders_skipped:missing_original")

    for element in document.elements:
        updated = element
        if element.element_type in _FIGURE_TYPES:
            asset_id = deterministic_id("canonical_figure", str(element.element_id))
            object_key = parse_figure_asset_key(
                tenant_id=tenant.tenant_id,
                document_id=document.document_id,
                version_id=document.version_id,
                attempt_id=attempt_id,
                asset_id=asset_id,
            )
            if is_pdf and original_bytes:
                bbox = _bbox_for_element(element)
                try:
                    png = await asyncio.to_thread(
                        render_visual_png, original_bytes, element.page_start, bbox
                    )
                except Exception as exc:
                    warnings.append(
                        f"figure_render_failed:{element.element_id}:{type(exc).__name__}"
                    )
                    logger.warning(
                        "canonical_figure_render_failed",
                        element_id=str(element.element_id),
                        error=str(exc),
                    )
                    updated_elements.append(updated)
                    continue
                stored = await _put_asset(object_store, tenant, object_key, png, "image/png")
                assets_by_id[asset_id] = DocumentAsset(
                    asset_id=asset_id,
                    asset_type="figure",
                    mime_type="image/png",
                    object_key=object_key,
                    page_number=element.page_start,
                    element_id=element.element_id,
                    content_hash=stored[0],
                    byte_size=stored[1],
                )
                updated = element.model_copy(update={"source_asset_id": asset_id})
        elif isinstance(element, TableElement):
            asset_id = deterministic_id("canonical_table", str(element.element_id))
            object_key = parse_table_asset_key(
                tenant_id=tenant.tenant_id,
                document_id=document.document_id,
                version_id=document.version_id,
                attempt_id=attempt_id,
                asset_id=asset_id,
            )
            payload = element.table.model_dump(mode="json")
            raw = json.dumps(payload, default=str).encode("utf-8") or b"{}"
            stored = await _put_asset(object_store, tenant, object_key, raw, "application/json")
            assets_by_id[asset_id] = DocumentAsset(
                asset_id=asset_id,
                asset_type="table",
                mime_type="application/json",
                object_key=object_key,
                page_number=element.page_start,
                element_id=element.element_id,
                content_hash=stored[0],
                byte_size=stored[1],
            )
            updated = element.model_copy(update={"source_asset_id": asset_id})
        updated_elements.append(updated)

    updated_document = document.model_copy(
        update={
            "elements": updated_elements,
            "assets": list(assets_by_id.values()),
        }
    )
    store = CanonicalStore(object_store)
    await store.write_from_document(tenant, updated_document, attempt_id=attempt_id)
    return updated_document, warnings


def _is_pdf(mime_type: str, filename: str) -> bool:
    return mime_type.lower() == "application/pdf" or filename.lower().endswith(".pdf")


def _bbox_for_element(element: DocumentElement) -> BoundingBox | None:
    for box in element.bounding_boxes:
        if box.page_number == element.page_start:
            return box
    return element.bounding_boxes[0] if element.bounding_boxes else None


async def _put_asset(
    object_store: ObjectStore,
    tenant: TenantContext,
    object_key: str,
    data: bytes,
    content_type: str,
) -> tuple[str, int]:
    payload = data if data else b"\n"
    digest = content_sha256_hex(payload)
    await object_store.put_bytes(
        tenant,
        object_key=object_key,
        data=payload,
        content_type=content_type,
        content_hash=digest,
    )
    return digest, len(payload)
