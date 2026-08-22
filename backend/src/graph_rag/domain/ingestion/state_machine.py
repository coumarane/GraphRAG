"""Ingestion state machine: transitions, progress and idempotency."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import IngestionStageRecord
from graph_rag.domain.ingestion.stages import (
    INGESTION_STAGE_ORDER,
    STAGE_WEIGHTS,
    SUCCESSFUL_STAGE_STATUSES,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.shared.exceptions import IngestionError, ValidationError


class StageRecord(BaseModel):
    """In-memory view of a persisted stage row."""

    model_config = ConfigDict(extra="forbid")

    stage: IngestionStageName
    status: StageStatus = StageStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    idempotency_key: str | None = None
    config_fingerprint: str | None = None
    warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class IngestionProgress(BaseModel):
    """Progress snapshot exposed to API/CLI (no ETA promise)."""

    model_config = ConfigDict(extra="forbid")

    current_stage: IngestionStageName | None
    completed_stages: list[IngestionStageName]
    pages_processed: int = Field(ge=0)
    elements_processed: int = Field(ge=0)
    estimated_completion_percent: float = Field(ge=0.0, le=100.0)
    latest_warning: str | None = None
    retry_count: int = Field(ge=0)


@dataclass
class IngestionStateMachine:
    """Pure domain state machine for a single ingestion run."""

    stages: dict[IngestionStageName, StageRecord] = field(default_factory=dict)
    run_status: IngestionRunStatus = IngestionRunStatus.PENDING
    pages_processed: int = 0
    elements_processed: int = 0

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = {
                name: StageRecord(stage=name, status=StageStatus.PENDING)
                for name in INGESTION_STAGE_ORDER
            }

    @staticmethod
    def build_idempotency_key(
        *,
        tenant_id: UUID | str,
        version_id: UUID | str,
        stage: IngestionStageName,
        config_fingerprint: str,
        content_hash: str,
    ) -> str:
        """Build the minimum idempotency key inputs from specs/04."""
        material = "|".join(
            [
                str(tenant_id),
                str(version_id),
                stage.value,
                config_fingerprint,
                content_hash.lower(),
            ]
        )
        return sha256(material.encode("utf-8")).hexdigest()

    def get_stage(self, stage: IngestionStageName) -> StageRecord:
        try:
            return self.stages[stage]
        except KeyError as exc:
            raise ValidationError(
                "Unknown ingestion stage",
                details={"stage": stage.value},
            ) from exc

    def current_stage(self) -> IngestionStageName | None:
        """Return the active or next pending stage."""
        for name in INGESTION_STAGE_ORDER:
            status = self.stages[name].status
            if status is StageStatus.RUNNING:
                return name
        for name in INGESTION_STAGE_ORDER:
            if self.stages[name].status is StageStatus.PENDING:
                return name
        return None

    def completed_stages(self) -> list[IngestionStageName]:
        return [
            name
            for name in INGESTION_STAGE_ORDER
            if self.stages[name].status in SUCCESSFUL_STAGE_STATUSES
        ]

    def estimated_completion_percent(self) -> float:
        total = sum(STAGE_WEIGHTS[name] for name in INGESTION_STAGE_ORDER)
        done = sum(
            STAGE_WEIGHTS[name]
            for name in INGESTION_STAGE_ORDER
            if self.stages[name].status in SUCCESSFUL_STAGE_STATUSES
        )
        running = self.current_stage()
        if running is not None and self.stages[running].status is StageStatus.RUNNING:
            done += STAGE_WEIGHTS[running] * 0.5
        return round(min(100.0, (done / total) * 100.0), 2)

    def progress(self) -> IngestionProgress:
        latest_warning: str | None = None
        retry_count = 0
        for name in reversed(INGESTION_STAGE_ORDER):
            record = self.stages[name]
            retry_count += max(0, record.attempt_count - 1)
            if latest_warning is None and record.warning:
                latest_warning = record.warning
        return IngestionProgress(
            current_stage=self.current_stage(),
            completed_stages=self.completed_stages(),
            pages_processed=self.pages_processed,
            elements_processed=self.elements_processed,
            estimated_completion_percent=self.estimated_completion_percent(),
            latest_warning=latest_warning,
            retry_count=retry_count,
        )

    def should_skip_on_resume(
        self,
        stage: IngestionStageName,
        *,
        idempotency_key: str,
        config_fingerprint: str,
    ) -> bool:
        """Skip completed stages only when fingerprint/key still match."""
        record = self.get_stage(stage)
        if record.status not in {
            StageStatus.COMPLETED,
            StageStatus.COMPLETED_WITH_WARNINGS,
            StageStatus.SKIPPED,
        }:
            return False
        return (
            record.idempotency_key == idempotency_key
            and record.config_fingerprint == config_fingerprint
        )

    def reset_stale_running(self) -> list[IngestionStageName]:
        """Turn abandoned RUNNING rows back into PENDING so resume can continue."""
        reset: list[IngestionStageName] = []
        for name, record in self.stages.items():
            if record.status is StageStatus.RUNNING:
                record.status = StageStatus.PENDING
                reset.append(name)
        if reset and self.run_status is IngestionRunStatus.RUNNING:
            self.run_status = IngestionRunStatus.PENDING
        return reset

    def mark_running(
        self,
        stage: IngestionStageName,
        *,
        idempotency_key: str,
        config_fingerprint: str,
    ) -> StageRecord:
        record = self.get_stage(stage)
        if record.status is StageStatus.RUNNING:
            raise IngestionError(
                "Stage is already running",
                details={"stage": stage.value},
            )
        if record.status in {StageStatus.COMPLETED, StageStatus.COMPLETED_WITH_WARNINGS}:
            raise IngestionError(
                "Cannot restart a completed stage without fingerprint change",
                details={"stage": stage.value, "status": record.status.value},
            )
        if record.status is StageStatus.CANCELLED:
            raise IngestionError(
                "Cannot restart a cancelled stage",
                details={"stage": stage.value},
            )
        if self.run_status is IngestionRunStatus.CANCELLED:
            raise IngestionError("Cannot start stages on a cancelled run")

        self._assert_predecessors_successful(stage)
        record.status = StageStatus.RUNNING
        record.attempt_count += 1
        record.idempotency_key = idempotency_key
        record.config_fingerprint = config_fingerprint
        record.error_code = None
        record.error_message = None
        if self.run_status in {
            IngestionRunStatus.PENDING,
            IngestionRunStatus.FAILED,
            IngestionRunStatus.PARTIAL,
        }:
            self.run_status = IngestionRunStatus.RUNNING
        return record

    def mark_completed(
        self,
        stage: IngestionStageName,
        *,
        warning: str | None = None,
    ) -> StageRecord:
        record = self.get_stage(stage)
        if record.status is not StageStatus.RUNNING:
            raise IngestionError(
                "Only running stages can be completed",
                details={"stage": stage.value, "status": record.status.value},
            )
        record.status = StageStatus.COMPLETED_WITH_WARNINGS if warning else StageStatus.COMPLETED
        record.warning = warning
        if stage is IngestionStageName.FINALIZE:
            self.run_status = (
                IngestionRunStatus.COMPLETED_WITH_WARNINGS
                if self._has_warning_stages()
                else IngestionRunStatus.COMPLETED
            )
        return record

    def mark_skipped(self, stage: IngestionStageName, *, reason: str | None = None) -> StageRecord:
        record = self.get_stage(stage)
        if record.status not in {StageStatus.PENDING, StageStatus.RUNNING}:
            raise IngestionError(
                "Only pending or running stages can be skipped",
                details={"stage": stage.value, "status": record.status.value},
            )
        if stage is IngestionStageName.FINALIZE:
            raise IngestionError("FINALIZE cannot be skipped")
        record.status = StageStatus.SKIPPED
        record.warning = reason
        return record

    def mark_failed(
        self,
        stage: IngestionStageName,
        *,
        error_code: str,
        error_message: str,
        partial: bool = False,
    ) -> StageRecord:
        record = self.get_stage(stage)
        if record.status not in {StageStatus.RUNNING, StageStatus.PENDING}:
            raise IngestionError(
                "Only pending or running stages can fail",
                details={"stage": stage.value, "status": record.status.value},
            )
        record.status = StageStatus.FAILED
        record.error_code = error_code
        record.error_message = error_message
        self.run_status = IngestionRunStatus.PARTIAL if partial else IngestionRunStatus.FAILED
        return record

    def cancel(self) -> None:
        if self.run_status in {
            IngestionRunStatus.COMPLETED,
            IngestionRunStatus.COMPLETED_WITH_WARNINGS,
        }:
            raise IngestionError("Cannot cancel a completed run")
        for name, record in self.stages.items():
            if record.status in {StageStatus.PENDING, StageStatus.RUNNING}:
                record.status = StageStatus.CANCELLED
                self.stages[name] = record
        self.run_status = IngestionRunStatus.CANCELLED

    def can_finalize(self) -> bool:
        """FINALIZE is allowed only when all prior stages succeeded or were skipped."""
        for name in INGESTION_STAGE_ORDER:
            if name is IngestionStageName.FINALIZE:
                break
            if self.stages[name].status not in SUCCESSFUL_STAGE_STATUSES:
                return False
        return True

    def _assert_predecessors_successful(self, stage: IngestionStageName) -> None:
        if stage is IngestionStageName.VALIDATE:
            return
        index = INGESTION_STAGE_ORDER.index(stage)
        for prior in INGESTION_STAGE_ORDER[:index]:
            status = self.stages[prior].status
            if status not in SUCCESSFUL_STAGE_STATUSES:
                raise IngestionError(
                    "Predecessor stage is not successful",
                    details={
                        "stage": stage.value,
                        "predecessor": prior.value,
                        "predecessor_status": status.value,
                    },
                )

    def _has_warning_stages(self) -> bool:
        return any(
            record.status is StageStatus.COMPLETED_WITH_WARNINGS or bool(record.warning)
            for record in self.stages.values()
        )


def initial_stage_records() -> list[StageRecord]:
    """Create pending records for every pipeline stage."""
    return [StageRecord(stage=name) for name in INGESTION_STAGE_ORDER]


def build_persisted_stage_records(
    *,
    tenant_id: UUID,
    ingestion_run_id: UUID,
) -> list[IngestionStageRecord]:
    """Create pending ``IngestionStageRecord`` rows for a new run."""
    return [
        IngestionStageRecord(
            stage_id=new_id(),
            tenant_id=tenant_id,
            ingestion_run_id=ingestion_run_id,
            stage=name,
            status=StageStatus.PENDING,
        )
        for name in INGESTION_STAGE_ORDER
    ]
