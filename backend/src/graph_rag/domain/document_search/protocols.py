"""Repository port for document/field search."""

from __future__ import annotations

from typing import Protocol

from graph_rag.domain.document_search.models import DocumentSearchQuery, DocumentSearchResult
from graph_rag.domain.tenant import TenantContext


class DocumentSearchRepository(Protocol):
    """Search documents by metadata columns and/or extracted field values.

    Implementations only enforce tenant scoping. Fine-grained ABAC
    (security labels/clearance) is intentionally NOT applied here -- the
    caller must run the result through
    ``application.authorization.filters.filter_authorized_documents`` before
    returning it, exactly like ``GET /documents`` already does.
    """

    async def search(
        self,
        tenant: TenantContext,
        query: DocumentSearchQuery,
    ) -> DocumentSearchResult:
        """Return the tenant-scoped candidate pool matching ``query``."""
        ...
