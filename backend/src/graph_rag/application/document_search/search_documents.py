"""Application facade for document/field search."""

from __future__ import annotations

from graph_rag.application.authorization.filters import filter_authorized_documents
from graph_rag.application.authorization.service import PolicyAuthorizationService
from graph_rag.domain.document_search.models import DocumentSearchQuery, DocumentSearchResult
from graph_rag.domain.document_search.protocols import DocumentSearchRepository
from graph_rag.domain.tenant import TenantContext


class SearchDocumentsService:
    """Search documents, then enforce ABAC before returning results.

    The repository only scopes by tenant; fine-grained authorization
    (security labels/clearance) is applied here, same as ``GET /documents``.
    """

    def __init__(
        self,
        repository: DocumentSearchRepository,
        authorization: PolicyAuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def search(
        self,
        tenant: TenantContext,
        query: DocumentSearchQuery,
    ) -> DocumentSearchResult:
        # Over-fetch enough candidates to survive ABAC filtering, then trim to
        # the requested page -- mirrors GET /documents's list_documents route,
        # which over-fetches for the same reason (some rows get filtered out
        # by authorization after the SQL query already ran).
        overfetch = query.model_copy(
            update={"offset": 0, "limit": max(query.offset + query.limit, 200)}
        )
        candidates = await self._repository.search(tenant, overfetch)
        allowed_documents = filter_authorized_documents(
            self._authorization,
            tenant,
            [hit.document for hit in candidates.items],
        )
        allowed_ids = {document.document_id for document in allowed_documents}
        allowed_hits = [
            hit for hit in candidates.items if hit.document.document_id in allowed_ids
        ]
        total = len(allowed_hits)
        page = allowed_hits[query.offset : query.offset + query.limit]
        return DocumentSearchResult(items=page, total=total)
