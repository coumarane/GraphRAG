"""Document Intelligence model/field catalog routes.

Read/write model *definitions* only (Phase 2) -- no extraction runs exist
yet. Built-in models are static data (``application.document_intelligence
.catalog``); custom models are tenant-owned rows created here.
"""

from __future__ import annotations

from fastapi import APIRouter

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import (
    DocumentIntelligenceModelCreateRequest,
    DocumentIntelligenceModelListResponse,
    DocumentIntelligenceModelResponse,
    FieldEntityMapping,
    ModelFieldResponse,
)
from graph_rag.application.authorization.gate import require_action
from graph_rag.application.document_intelligence.catalog import (
    BUILTIN_DOCUMENT_INTELLIGENCE_MODELS,
)
from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceModel,
    ModelType,
)
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.document_intelligence.records import (
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.ids import new_id

router = APIRouter(prefix="/document-intelligence", tags=["document-intelligence"])


def _builtin_response(model: DocumentIntelligenceModel) -> DocumentIntelligenceModelResponse:
    return DocumentIntelligenceModelResponse(
        model_key=model.model_key,
        model_id=None,
        name=model.name,
        model_type=model.model_type,
        version=model.version,
        is_builtin=True,
        fields=[
            ModelFieldResponse(
                name=field.name,
                label=field.label,
                field_type=field.field_type,
                default_selected=field.default_selected,
                promote_to_document_metadata=field.promote_to_document_metadata,
            )
            for field in model.fields
        ],
    )


def _custom_response(record: DocumentIntelligenceModelRecord) -> DocumentIntelligenceModelResponse:
    return DocumentIntelligenceModelResponse(
        model_key=record.model_key,
        model_id=record.model_id,
        name=record.name,
        model_type=ModelType(record.model_type),
        version=record.version,
        is_builtin=record.is_builtin,
        fields=[
            ModelFieldResponse(
                name=field.name,
                label=field.label,
                field_type=field.field_type,  # type: ignore[arg-type]
                default_selected=field.default_selected,
                promote_to_document_metadata=field.promote_to_document_metadata,
            )
            for field in record.fields
        ],
        field_entity_mappings={
            name: FieldEntityMapping.model_validate(mapping)
            for name, mapping in record.field_entity_mappings.items()
        },
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/models", response_model=DocumentIntelligenceModelListResponse)
async def list_document_intelligence_models(
    tenant: TenantDep,
    container: ContainerDep,
) -> DocumentIntelligenceModelListResponse:
    require_action(container.require_authorization(), tenant, Action.DOCUMENT_UPLOAD)
    custom = await container.require_document_intelligence_model_repo().list_models(tenant)
    items = [_builtin_response(model) for model in BUILTIN_DOCUMENT_INTELLIGENCE_MODELS]
    items.extend(_custom_response(record) for record in custom)
    return DocumentIntelligenceModelListResponse(items=items)


@router.post("/models", status_code=201, response_model=DocumentIntelligenceModelResponse)
async def create_document_intelligence_model(
    body: DocumentIntelligenceModelCreateRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> DocumentIntelligenceModelResponse:
    require_action(container.require_authorization(), tenant, Action.DOCUMENT_UPLOAD)
    model_id = new_id()
    record = DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant.tenant_id,
        model_key=body.model_key.strip().lower(),
        name=body.name,
        model_type=ModelType.CUSTOM,
        is_builtin=False,
        created_by_user_id=tenant.user_id,
        field_entity_mappings={
            name: mapping.model_dump(mode="json")
            for name, mapping in body.field_entity_mappings.items()
        },
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant.tenant_id,
                name=field.name,
                label=field.label,
                field_type=field.field_type,
                default_selected=field.default_selected,
                promote_to_document_metadata=field.promote_to_document_metadata,
                sort_order=index,
            )
            for index, field in enumerate(body.fields)
        ],
    )
    created = await container.require_document_intelligence_model_repo().create_model(
        tenant, record
    )
    await container.commit_db()
    return _custom_response(created)
