"""Typed application exception hierarchy.

Exceptions carry a stable machine-readable ``code`` suitable for RFC 9457
problem details. Callers must not catch bare ``Exception`` to swallow failures.
"""

from __future__ import annotations

from typing import Any


class EnterpriseRagError(Exception):
    """Base error for all application failures."""

    code: str = "graph_rag_error"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        """Return a safe, serializable error payload."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class TransientError(EnterpriseRagError):
    """Retryable failure (network blip, lock contention, rate limit)."""

    code = "transient_error"
    http_status = 503


class RateLimitError(TransientError):
    """Caller exceeded a rate limit."""

    code = "rate_limit_exceeded"
    http_status = 429


class PermanentError(EnterpriseRagError):
    """Non-retryable failure."""

    code = "permanent_error"
    http_status = 400


class ConfigurationError(PermanentError):
    """Invalid or missing configuration."""

    code = "configuration_error"
    http_status = 500


class ValidationError(PermanentError):
    """Input or contract validation failure."""

    code = "validation_error"
    http_status = 422


class AuthorizationError(PermanentError):
    """Caller is not permitted to perform the operation."""

    code = "authorization_error"
    http_status = 403


class AuthenticationError(PermanentError):
    """Caller is not authenticated."""

    code = "authentication_error"
    http_status = 401


class TenantError(PermanentError):
    """Tenant context missing, invalid, or isolation violation."""

    code = "tenant_error"
    http_status = 403


class QuotaExceededError(PermanentError):
    """Caller exceeded a quota limit (maps to HTTP 429)."""

    code = "quota_exceeded"
    http_status = 429


class NotFoundError(PermanentError):
    """Requested resource does not exist in the authorized scope."""

    code = "not_found"
    http_status = 404


class ConflictError(PermanentError):
    """State conflict such as duplicate version or concurrent mutation."""

    code = "conflict"
    http_status = 409


class StorageError(EnterpriseRagError):
    """Persistence adapter failure (PostgreSQL, MinIO, Qdrant, Neo4j, Redis)."""

    code = "storage_error"
    http_status = 500


class ParserError(EnterpriseRagError):
    """Document parser or OCR failure."""

    code = "parser_error"
    http_status = 422


class UnsupportedDocumentError(ParserError, PermanentError):
    """Document type or profile is not supported."""

    code = "unsupported_document"
    http_status = 422


class ModelError(EnterpriseRagError):
    """LLM, vision, embedding or reranker failure."""

    code = "model_error"
    http_status = 502


class GraphError(EnterpriseRagError):
    """Knowledge-graph extraction, resolution or query failure."""

    code = "graph_error"
    http_status = 500


class IngestionError(EnterpriseRagError):
    """Ingestion orchestration or stage failure."""

    code = "ingestion_error"
    http_status = 500


class RetrievalError(EnterpriseRagError):
    """Retrieval or answer-generation failure."""

    code = "retrieval_error"
    http_status = 500


class CitationValidationError(RetrievalError, PermanentError):
    """Generated answer cited evidence that was not retrieved."""

    code = "citation_validation_error"
    http_status = 500
