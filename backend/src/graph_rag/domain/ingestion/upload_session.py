"""Intake session. It is not a document."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UploadSessionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REJECTED = "rejected"


class UploadSessionRecord(BaseModel):
    """Temporary reservation for one member upload or remote fetch."""

    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    tenant_id: UUID
    user_id: UUID | None = None
    document_id: UUID | None = None
    version_id: UUID | None = None
    staging_object_key: str | None = None
    final_object_key: str | None = None
    source_filename: str
    title: str | None = None
    declared_byte_size: int = Field(ge=1, le=104_857_600)
    actual_byte_size: int | None = None
    content_hash: str | None = None
    etag: str | None = None
    object_version_id: str | None = None
    mime_type: str | None = None
    status: UploadSessionStatus = UploadSessionStatus.PENDING
    expires_at: datetime
    ingestion_run_id: UUID | None = None
    source_url: str | None = None
    document_reservation_id: UUID | None = None
    storage_reservation_id: UUID | None = None
    error_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
