"""PostgreSQL ORM model package."""

from graph_rag.infrastructure.persistence.postgres.models.abac import (
    AuthorizationPolicyModel,
    PolicyVersionModel,
    QuotaAssignmentModel,
    QuotaPlanModel,
    QuotaReservationModel,
    QuotaUsageEventModel,
    TenantMembershipModel,
    UsageCounterModel,
)
from graph_rag.infrastructure.persistence.postgres.models.conversations import (
    ChatConversationModel,
    ChatMessageModel,
    ChatProjectModel,
)
from graph_rag.infrastructure.persistence.postgres.models.document_intelligence import (
    DocumentExtractedFieldModel,
    DocumentExtractionRunModel,
    DocumentIntelligenceModelFieldModel,
    DocumentIntelligenceModelModel,
)
from graph_rag.infrastructure.persistence.postgres.models.documents import (
    DocumentModel,
    DocumentVersionModel,
    TenantModel,
)
from graph_rag.infrastructure.persistence.postgres.models.ingestion import (
    IngestionRunModel,
    IngestionStageModel,
    ParserAttemptModel,
)
from graph_rag.infrastructure.persistence.postgres.models.outbox import (
    IngestionDeadLetterModel,
    OutboxEventModel,
)
from graph_rag.infrastructure.persistence.postgres.models.parsing_audit import (
    ContentLossRecordModel,
    DocumentParseReportModel,
    ElementParseReportModel,
    IngestionIssueModel,
    PageParseReportModel,
    ProcessingStageRunModel,
    RoutingDecisionModel,
)
from graph_rag.infrastructure.persistence.postgres.models.plugins import (
    PluginConfigurationModel,
    PluginModel,
)
from graph_rag.infrastructure.persistence.postgres.models.usage import ModelUsageEventModel
from graph_rag.infrastructure.persistence.postgres.models.users import UserModel

__all__ = [
    "AuthorizationPolicyModel",
    "ChatConversationModel",
    "ChatMessageModel",
    "ChatProjectModel",
    "ContentLossRecordModel",
    "DocumentExtractedFieldModel",
    "DocumentExtractionRunModel",
    "DocumentIntelligenceModelFieldModel",
    "DocumentIntelligenceModelModel",
    "DocumentModel",
    "DocumentParseReportModel",
    "DocumentVersionModel",
    "ElementParseReportModel",
    "IngestionDeadLetterModel",
    "IngestionIssueModel",
    "IngestionRunModel",
    "IngestionStageModel",
    "ModelUsageEventModel",
    "OutboxEventModel",
    "PageParseReportModel",
    "ParserAttemptModel",
    "PluginConfigurationModel",
    "PluginModel",
    "PolicyVersionModel",
    "ProcessingStageRunModel",
    "QuotaAssignmentModel",
    "QuotaPlanModel",
    "QuotaReservationModel",
    "QuotaUsageEventModel",
    "RoutingDecisionModel",
    "TenantMembershipModel",
    "TenantModel",
    "UsageCounterModel",
    "UserModel",
]
