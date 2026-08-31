"""PostgreSQL repository adapters."""

from graph_rag.infrastructure.persistence.postgres.repositories.conversations import (
    SqlAlchemyChatConversationRepository,
    SqlAlchemyChatProjectRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.document_intelligence import (
    SqlAlchemyDocumentExtractionRepository,
    SqlAlchemyDocumentIntelligenceModelRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.document_search import (
    SqlAlchemyDocumentSearchRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.documents import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)

__all__ = [
    "SqlAlchemyChatConversationRepository",
    "SqlAlchemyChatProjectRepository",
    "SqlAlchemyDocumentExtractionRepository",
    "SqlAlchemyDocumentIntelligenceModelRepository",
    "SqlAlchemyDocumentRepository",
    "SqlAlchemyDocumentSearchRepository",
    "SqlAlchemyIngestionRepository",
    "SqlAlchemyTenantRepository",
]
