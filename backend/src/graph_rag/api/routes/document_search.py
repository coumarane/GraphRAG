"""Cross-document search over metadata columns and extracted structured fields.

Deliberately a separate ``POST`` endpoint rather than an extension of
``GET /documents``: the filter payload (field predicates, date ranges) is
richer than comfortably fits query params, and this avoids a breaking
contract change to that widely-used listing endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import (
    DocumentResponse,
    DocumentSearchHitItem,
    DocumentSearchRequest,
    DocumentSearchResponse,
    ExtractedFieldItem,
)
from graph_rag.domain.document_intelligence.records import DocumentExtractedFieldRecord
from graph_rag.domain.document_search.models import (
    DocumentSearchHit,
    DocumentSearchQuery,
    FieldFilter,
    FieldFilterOperator,
)
from graph_rag.domain.ingestion.records import DocumentRecord

router = APIRouter(prefix="/documents", tags=["documents"])


def _document_response(document: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        title=document.title,
        document_type=document.document_type,
        status=document.status.value,
        current_version_id=document.current_version_id,
        tags=list(document.tags),
        security_labels=list(document.security_labels),
        metadata=dict(document.metadata),
    )


def _extracted_field_response(field: DocumentExtractedFieldRecord) -> ExtractedFieldItem:
    return ExtractedFieldItem(
        name=field.name,
        value=field.value,
        normalized_value=field.normalized_value,
        confidence=field.confidence,
        confidence_band=field.confidence_band,
        page=field.page,
        source_text=field.source_text,
        extraction_method=field.extraction_method,
        model_name=field.model_name,
    )


def _hit_response(hit: DocumentSearchHit) -> DocumentSearchHitItem:
    return DocumentSearchHitItem(
        document=_document_response(hit.document),
        matched_fields=[_extracted_field_response(field) for field in hit.matched_fields],
    )


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(
    body: DocumentSearchRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> DocumentSearchResponse:
    query = DocumentSearchQuery(
        text=body.text,
        document_type=body.document_type,
        status=body.status,
        tags=list(body.tags),
        department=body.department,
        country=body.country,
        business_unit=body.business_unit,
        classification=body.classification,
        created_after=body.created_after,
        created_before=body.created_before,
        field_filters=[
            FieldFilter(
                name=item.name,
                operator=FieldFilterOperator(item.operator),
                value=item.value,
                value_to=item.value_to,
            )
            for item in body.field_filters
        ],
        offset=body.offset,
        limit=body.limit,
    )
    result = await container.require_document_search().search(tenant, query)
    return DocumentSearchResponse(
        items=[_hit_response(hit) for hit in result.items],
        total=result.total,
        offset=body.offset,
        limit=body.limit,
    )
